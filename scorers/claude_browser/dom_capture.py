"""Failure-time DOM evidence for the browser scorer.

When a brittle UI selector drifts, the downstream triage fixer (DeepSeek) never
sees the live page. This module captures apt evidence at the moment of failure
so it can ground a fix instead of guessing. Every brittle interaction should go
through :func:`wait_or_capture`; on timeout it attaches a ``dom_context`` to the
raised :class:`ScoringError`, which the canary forwards into the escalation
packet.

``dom_context`` bundles three complementary strategies so it works whether the
break is a popup, a moved top-level element, or a wholesale restructure:

* ``overlays``   - outerHTML + option labels of any open menu/modal, anchored on
                   stable ARIA roles / portal mounts (not brittle text).
* ``candidates`` - nearest elements to the *failed* selector, ranked by how many
                   of its tokens they still match, with their real attributes -
                   this is what usually tells DeepSeek "testid X became Y".
* ``page_html``  - the whole page, cheaply pruned (scripts/styles/svg/base64/
                   comments stripped, whitespace collapsed, size-capped). Big but
                   high-recall; gated by ``attach_page_html`` for spend control.
"""

from __future__ import annotations

import re

from playwright.async_api import Page

from models import ScoringError

_PAGE_HTML_CAP = 150_000  # chars; hard ceiling so a pathological page can't blow up a request

# --- open overlays (popups / menus / modals) -------------------------------
_OVERLAY_JS = r"""
() => {
  const MAX_HTML = 4000, MAX_OVERLAYS = 2, MAX_OPTIONS = 40;
  const ANCHOR_SEL = [
    '[role="menu"]', '[role="listbox"]', '[role="dialog"]', '[aria-modal="true"]',
    '[data-radix-popper-content-wrapper]', '[data-testid*="dropdown"]',
    '[data-testid*="modal"]', '[data-state="open"]'
  ].join(',');
  const OPTION_SEL = [
    '[role="menuitemradio"]', '[role="menuitemcheckbox"]', '[role="menuitem"]',
    '[role="option"]', 'button', 'a'
  ].join(',');
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const clip = (s, n) => (s && s.length > n ? s.slice(0, n) + '…[truncated]' : s);
  const candidates = [];
  document.querySelectorAll(ANCHOR_SEL).forEach((el) => {
    // A button that ANCHOR_SEL matched (e.g. data-testid*="dropdown") is the
    // *trigger*, not the popup it opens -- never treat it as an overlay root.
    if (visible(el) && el.tagName !== 'BUTTON') candidates.push(el);
  });
  // Portal fallback: late <body> children where popovers mount -- but skip the
  // app mount (#root/#__next) and anything too large to be a popup, so we grab
  // the modal, not the whole application.
  Array.from(document.body.children).slice(-6).forEach((el) => {
    if (!visible(el) || candidates.includes(el)) return;
    if (el.id === 'root' || el.id === '__next') return;
    if (el.querySelectorAll('*').length > 500) return;
    candidates.push(el);
  });
  const roots = candidates.filter((el) => !candidates.some((o) => o !== el && o.contains(el)));
  // Rank real overlays first so weak anchors can't squeeze them out of the cap:
  // strong ARIA roles beat testid/portal heuristics, and roots with selectable
  // options beat empty shells.
  const prio = (el) => {
    const role = el.getAttribute('role');
    if (['menu', 'listbox', 'dialog'].includes(role) || el.getAttribute('aria-modal') === 'true') return 0;
    if (el.matches('[data-radix-popper-content-wrapper],[data-state="open"]')) return 1;
    return 2;
  };
  roots.sort((a, b) => {
    const optDiff = (b.querySelectorAll(OPTION_SEL).length ? 1 : 0) - (a.querySelectorAll(OPTION_SEL).length ? 1 : 0);
    return optDiff !== 0 ? optDiff : prio(a) - prio(b);
  });
  return roots.slice(0, MAX_OVERLAYS).map((el) => ({
    anchor: el.getAttribute('role') || el.getAttribute('data-testid')
      || (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')),
    options: Array.from(new Set(
      Array.from(el.querySelectorAll(OPTION_SEL))
        .map((o) => (o.innerText || o.getAttribute('aria-label') || '').trim())
        .filter(Boolean)
    )).slice(0, MAX_OPTIONS).map((t) => clip(t, 120)),
    html: clip(el.outerHTML, MAX_HTML),
  }));
}
"""

# --- nearest candidates (selector relaxation) ------------------------------
# Decompose the failed selector into atomic tokens (tag / [attr=val] / .class /
# playwright :text-is/:has-text) and rank every element by how many tokens it
# still matches. Partial matches with the highest score are the drifted target;
# reporting their real attributes shows DeepSeek exactly what changed.
_CANDIDATES_JS = r"""
(selector) => {
  const MAX = 5, ATTRS = ['id','class','role','data-testid','aria-label','placeholder',
                          'name','type','contenteditable','href'];
  const attrRe = /\[([\w-]+)(?:[~|^$*]?=["']?([^"'\]]*)["']?)?\]/g;
  const textRe = /:(?:text-is|has-text|text)\(\s*["']([^"']+)["']\s*\)/g;
  const classRe = /\.([\w-]+)/g;
  const tagMatch = selector.match(/^\s*([a-zA-Z][\w-]*)/);
  const tag = tagMatch ? tagMatch[1].toLowerCase() : null;
  const attrs = [], texts = [], classes = [];
  let m;
  while ((m = attrRe.exec(selector))) attrs.push({ name: m[1], value: m[2] ?? null });
  while ((m = textRe.exec(selector))) texts.push(m[1]);
  // Strip [attr] and :pseudo(...) content first so text like "Sonnet 4.6" in a
  // :text-is() pseudo doesn't get mis-parsed as a ".6" class token.
  const noBrackets = selector.replace(/\[[^\]]*\]/g, '').replace(/:[\w-]+\([^)]*\)/g, '');
  while ((m = classRe.exec(noBrackets))) classes.push(m[1]);
  if (!tag && !attrs.length && !texts.length && !classes.length) return [];

  const clip = (s, n) => (s && s.length > n ? s.slice(0, n) + '…' : s);
  const scored = [];
  for (const el of document.querySelectorAll('*')) {
    const matched = [], missing = [];
    if (tag) (el.tagName.toLowerCase() === tag ? matched : missing).push('tag=' + tag);
    for (const a of attrs) {
      const v = el.getAttribute(a.name);
      const ok = a.value !== null ? v === a.value : v !== null;
      (ok ? matched : missing).push(a.value !== null ? a.name + '=' + a.value : a.name);
    }
    for (const c of classes) (el.classList.contains(c) ? matched : missing).push('.' + c);
    for (const t of texts) (((el.innerText || '').includes(t)) ? matched : missing).push('text:' + t);
    if (matched.length && missing.length) scored.push({ el, matched, missing });
  }
  scored.sort((a, b) => b.matched.length - a.matched.length);
  return scored.slice(0, MAX).map(({ el, matched, missing }) => {
    const actual = { tag: el.tagName.toLowerCase() };
    for (const a of ATTRS) { const v = el.getAttribute(a); if (v !== null) actual[a] = clip(v, 160); }
    return { matched, missing, actual_attrs: actual, html: clip(el.outerHTML, 500) };
  });
}
"""


def prune_html(html: str, cap: int = _PAGE_HTML_CAP) -> str:
    """Cheap, model-free prune: strip the noise that never helps a selector fix
    (scripts, styles, svg, comments, base64 data URIs), collapse whitespace, and
    hard-cap the size. Typically removes 80-95% of bytes while keeping every tag
    and its role/testid/aria/class attributes."""
    if not html:
        return ""
    html = re.sub(r"(?is)<(script|style|svg|noscript|template)\b.*?</\1>", "", html)
    html = re.sub(r"(?s)<!--.*?-->", "", html)
    html = re.sub(r'(?i)\s(?:src|href|xlink:href)="data:[^"]*"', "", html)
    html = re.sub(r"\s+", " ", html).strip()
    if len(html) > cap:
        html = html[:cap] + "…[truncated]"
    return html


async def capture_dom_context(
    page: Page, attempted: str, what: str, attach_page_html: bool = True
) -> dict:
    """Best-effort structural evidence about the page at failure time. Never
    raises: a capture failure must not mask the original error."""
    ctx: dict = {
        "looking_for": what,
        "attempted_selector": attempted,
        "overlays": [],
        "candidates": [],
        "page_html": None,
        "capture_error": None,
    }
    errors = []
    try:
        ctx["overlays"] = await page.evaluate(_OVERLAY_JS)
    except Exception as exc:  # noqa: BLE001 - best-effort
        errors.append("overlays:" + repr(exc)[:120])
    try:
        ctx["candidates"] = await page.evaluate(_CANDIDATES_JS, attempted)
    except Exception as exc:  # noqa: BLE001
        errors.append("candidates:" + repr(exc)[:120])
    if attach_page_html:
        try:
            ctx["page_html"] = prune_html(await page.content())
        except Exception as exc:  # noqa: BLE001
            errors.append("page_html:" + repr(exc)[:120])
    ctx["capture_error"] = "; ".join(errors) or None
    return ctx


def _summary(dom_context: dict) -> str:
    bits = []
    cands = dom_context.get("candidates") or []
    if cands:
        bits.append(f"nearest={cands[0].get('actual_attrs')}")
    overlays = dom_context.get("overlays") or []
    if overlays and overlays[0].get("options"):
        bits.append(f"offered={overlays[0]['options'][:12]}")
    return "; ".join(bits) or "no candidates found"


async def wait_or_capture(
    page: Page,
    selector: str,
    *,
    what: str,
    timeout: int = 10_000,
    state: str = "visible",
    attach_page_html: bool = True,
):
    """Wait for ``selector`` and return its (``.first``) Locator. On timeout,
    capture failure-time DOM evidence and raise ``ScoringError`` with a
    ``dom_context`` attribute the canary forwards to the triage packet.

    Route every brittle scorer interaction through this so no selector is ever
    left without evidence when it drifts."""
    locator = page.locator(selector).first
    try:
        await locator.wait_for(state=state, timeout=timeout)
        return locator
    except Exception as e:
        dom_context = await capture_dom_context(page, selector, what, attach_page_html)
        err = ScoringError(
            f"could not find {what} [{selector}]; {_summary(dom_context)}",
            raw_response="",
        )
        err.dom_context = dom_context
        raise err from e
