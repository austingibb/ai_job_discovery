"""Live canary: a layered precondition chain over broad preset search URLs.

Each layer is checked in order and the FIRST failing layer classifies the run:

  1. CDP connection alive        -> ENVIRONMENT_CDP_DOWN   (tell user; never a code fix)
  2. Logged in / not a login wall-> ENVIRONMENT_AUTH        (tell user; never a code fix)
  3. Results container present   -> URL_OR_STRUCTURE_DRIFT
  4. Listings parse              -> SCRAPER_SELECTOR_DRIFT
  5. Scorer parses a sample      -> SCORER_DRIFT

Core assumption: the presets are broad ("software" / "software engineer" across
all of the USA), so a healthy page that yields ZERO jobs always means breakage,
never a legitimately empty search.

Cross-preset logic:
  - All presets fail at the same layer  -> systemic real drift -> escalate.
  - One preset fails while others return healthy results with jobs -> the shared
    "software/USA" param shape means that points at the failing preset's fixture,
    not the scraper -> CANARY_MAINTENANCE (low priority, never a code fix).

Layers 1-2 are the only test-setup surface (we navigate directly to preset URLs,
so there is no UI filter automation). A failure there is ENVIRONMENT_*, reported
as canary/environment health, never as a scraper code bug.

This canary does detection and classification only. It never edits scraper code;
layer 4 reuses the real plugin scrape so that a downstream verify step exercises
the production selectors.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import requests
from playwright.sync_api import Page, sync_playwright

from config import _select_profile_dir, load_config, load_profile
from models import JobListing, UserProfile
from plugins.hiring_cafe.hiring_cafe import HiringCafePlugin
from plugins.linkedin.linkedin import LinkedInPlugin
from scorers.claude_browser.claude_browser import ClaudeBrowserScorer
from models import FailedResult

from canaries.presets import DEFAULT_PRESETS, Preset
from canaries.result import (
    LAYER_CLASSIFICATION,
    CanaryResult,
    Classification,
    Layer,
    PresetResult,
)

PLUGIN_CLASSES: dict[str, type] = {
    "hiring_cafe": HiringCafePlugin,
    "linkedin": LinkedInPlugin,
}

# What a healthy results container looks like per site. The canary must encode
# the expected-good shape; that is its whole job.
CONTAINER_SELECTORS: dict[str, str] = {
    "hiring_cafe": 'div.grid a[href^="/job/"]',
    "linkedin": (
        '[data-testid="lazy-column"] div[role="button"][componentkey]'
        ':has(button[aria-label$=" job"])'
    ),
}

LOGIN_MARKERS = ("login", "authwall", "signin", "sign-in", "checkpoint", "uas/login")

# Layer order, used to find the earliest (most fundamental) failing layer.
_LAYER_ORDER = [
    Layer.CDP,
    Layer.AUTH,
    Layer.RESULTS_CONTAINER,
    Layer.LISTINGS_PARSE,
    Layer.SCORER_PARSE,
]


def _git_commit() -> str | None:
    """Last-known-good commit, for the escalation packet."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _safe_snippet(page: Page, limit: int = 1500) -> dict:
    """Capture lightweight evidence about the current page."""
    snippet: dict = {}
    try:
        snippet["title"] = page.title()
    except Exception:
        snippet["title"] = None
    try:
        snippet["url"] = page.url
    except Exception:
        snippet["url"] = None
    try:
        snippet["body_html"] = page.locator("body").inner_html(timeout=3_000)[:limit]
    except Exception:
        snippet["body_html"] = None
    return snippet


# --- Layer checks ----------------------------------------------------------

def check_cdp(cdp_url: str) -> tuple[bool, dict]:
    """Layer 1: is the Chrome debug instance reachable over CDP?"""
    version_url = cdp_url.rstrip("/") + "/json/version"
    try:
        resp = requests.get(version_url, timeout=5)
        if resp.status_code == 200:
            return True, {"cdp_url": cdp_url, "browser": resp.json().get("Browser")}
        return False, {"cdp_url": cdp_url, "status_code": resp.status_code}
    except Exception as e:
        return False, {"cdp_url": cdp_url, "exception": repr(e)[:300]}


def check_auth(page: Page, preset: Preset) -> tuple[bool, dict]:
    """Layer 2: did the preset URL land on an authenticated page, not a login wall?"""
    final_url = page.url
    lowered = final_url.lower()
    on_login_wall = any(marker in lowered for marker in LOGIN_MARKERS)
    if on_login_wall:
        return False, {
            "attempted_url": preset.url,
            "redirect_target": final_url,
            "reason": "redirected to a login/authwall page",
        }
    return True, {"final_url": final_url}


def check_container(
    page: Page, plugin_name: str, selector_override: str | None = None
) -> tuple[bool, dict]:
    """Layer 3: is the expected results container present in the DOM?"""
    selector = selector_override or CONTAINER_SELECTORS[plugin_name]
    try:
        page.locator(selector).first.wait_for(state="visible", timeout=20_000)
        count = page.locator(selector).count()
        return True, {"selector": selector, "match_count": count}
    except Exception as e:
        evidence = {
            "selector": selector,
            "exception": repr(e)[:300],
            "dom_snippet": _safe_snippet(page),
        }
        return False, evidence


def parse_listings(
    plugin, page: Page, preset: Preset
) -> tuple[list[JobListing], bool, dict]:
    """Layer 4: do listings parse into JobListings with non-null key fields?

    Reuses the real plugin scrape so verification exercises production selectors.
    Because the presets are broad, a healthy container with zero parsed listings
    is breakage, not an empty search.
    """
    expected_shape = {"min_jobs": 1, "non_null_fields": ["title", "company", "url"]}
    try:
        listings = plugin._scrape_jobs(page)
    except Exception as e:
        return [], False, {
            "attempted_url": preset.url,
            "expected_shape": expected_shape,
            "exception": repr(e)[:300],
        }

    valid = [j for j in listings if j.title.strip() and j.url.strip()]
    actual_shape = {
        "job_count": len(listings),
        "valid_count": len(valid),
        "sample": [
            {"title": j.title, "company": j.company, "url": j.url}
            for j in listings[:3]
        ],
    }
    ok = len(valid) > 0
    return listings, ok, {
        "attempted_url": preset.url,
        "expected_shape": expected_shape,
        "actual_shape": actual_shape,
    }


def check_scorer(
    profile: UserProfile, sample: list[JobListing], scorer: ClaudeBrowserScorer
) -> tuple[bool, dict]:
    """Layer 5: does a small sample run through the scorer and parse via parser.py?"""
    try:
        results = scorer.score(profile, sample)
    except Exception as e:
        evidence = {"sample_size": len(sample), "exception": repr(e)[:300]}
        # Structural DOM of the popup that was open at failure time (model picker,
        # modal, ...), attached by the scorer. Gives the triage fixer the real
        # option labels / structure instead of a blind guess. See dom_capture.py.
        dom_context = getattr(e, "dom_context", None)
        if dom_context:
            evidence["dom_context"] = dom_context
        return False, evidence

    failed = [r for r in results if isinstance(r, FailedResult)]
    if failed or len(results) != len(sample):
        return False, {
            "sample_size": len(sample),
            "result_count": len(results),
            "failed_count": len(failed),
            "failed_reasons": [getattr(r, "reason", "") for r in failed][:3],
        }

    # Cleanup is part of the scorer's contract: a chat it cannot delete leaks
    # into the user's claude.ai history on every poll, invisibly (the scorer
    # deliberately doesn't fail scoring over it). Surface it as drift so the
    # fixer ladder gets the DOM evidence instead of the trail growing silently.
    cleanup_error = getattr(scorer, "last_cleanup_error", None)
    if cleanup_error:
        return False, {
            "sample_size": len(sample),
            "scoring": "succeeded; failure is chat cleanup only",
            "cleanup_error": cleanup_error,
        }

    return True, {"sample_size": len(sample), "result_types": [type(r).__name__ for r in results]}


# --- Orchestration ---------------------------------------------------------

def run_live_canary(
    presets: list[Preset] | None = None,
    cdp_url: str | None = None,
    run_scorer: bool = True,
    sample_size: int = 1,
    container_selector_override: str | None = None,
) -> CanaryResult:
    presets = presets or DEFAULT_PRESETS
    config = load_config()
    cdp_url = cdp_url or config["cdp_url"]
    commit = _git_commit()

    # Layer 1 is global: if the debug browser is unreachable, every preset fails here.
    cdp_ok, cdp_evidence = check_cdp(cdp_url)
    if not cdp_ok:
        presets_out = [
            PresetResult(
                name=p.name,
                url=p.url,
                healthy=False,
                failed_layer=Layer.CDP,
                classification=Classification.ENVIRONMENT_CDP_DOWN,
                evidence=cdp_evidence,
            )
            for p in presets
        ]
        return CanaryResult(
            classification=Classification.ENVIRONMENT_CDP_DOWN,
            healthy=False,
            escalate=True,
            summary="CDP unreachable; cannot connect to the Chrome debug instance. Start Chrome.",
            presets=presets_out,
            last_known_good_commit=commit,
        )

    # Layers 2-4 run inside one sync Playwright session. Layer 5 (scorer) runs
    # afterwards because the scorer opens its own async Playwright session.
    preset_results: list[PresetResult] = []
    scorer_samples: dict[str, list[JobListing]] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        for preset in presets:
            pr, listings = _run_preset_through_layer4(
                preset, context, container_selector_override
            )
            preset_results.append(pr)
            if pr.healthy and listings:  # passed layers 2-4, has listings
                scorer_samples[preset.name] = listings[:sample_size]

    # Layer 5: run the scorer once on a sample from the first healthy preset and
    # apply the outcome to every preset that reached this layer (the scorer is
    # preset-independent, so a failure here is systemic by nature).
    if run_scorer and scorer_samples:
        first_name, sample = next(iter(scorer_samples.items()))
        scorer = _build_scorer(config)
        profile = load_profile(_select_profile_dir(config["profile"]))
        ok, evidence = check_scorer(profile, sample, scorer)
        evidence["sampled_from_preset"] = first_name
        for pr in preset_results:
            if pr.name in scorer_samples:
                if ok:
                    pr.evidence["scorer"] = evidence
                else:
                    pr.healthy = False
                    pr.failed_layer = Layer.SCORER_PARSE
                    pr.classification = Classification.SCORER_DRIFT
                    pr.evidence["scorer"] = evidence

    return _aggregate(preset_results, commit, scorer_ran=run_scorer)


def _build_scorer(config: dict) -> ClaudeBrowserScorer:
    from config import load_scorer_config

    scorer_config = load_scorer_config("claude_browser")
    return ClaudeBrowserScorer(project_url=scorer_config.get("project_url"))


def _run_preset_through_layer4(
    preset: Preset, context, container_selector_override: str | None
) -> tuple[PresetResult, list[JobListing]]:
    pr = PresetResult(name=preset.name, url=preset.url, healthy=False)
    page = context.new_page()
    try:
        page.goto(preset.url, wait_until="domcontentloaded", timeout=30_000)

        # Layer 2: auth / login wall.
        ok, evidence = check_auth(page, preset)
        if not ok:
            pr.failed_layer = Layer.AUTH
            pr.classification = Classification.ENVIRONMENT_AUTH
            pr.evidence = evidence
            return pr, []

        # Layer 3: results container present.
        ok, evidence = check_container(page, preset.plugin, container_selector_override)
        if not ok:
            pr.failed_layer = Layer.RESULTS_CONTAINER
            pr.classification = Classification.URL_OR_STRUCTURE_DRIFT
            pr.evidence = evidence
            return pr, []

        # Layer 4: listings parse (real plugin scrape).
        plugin = PLUGIN_CLASSES[preset.plugin](search_filter_url=preset.url)
        listings, ok, evidence = parse_listings(plugin, page, preset)
        if not ok:
            pr.failed_layer = Layer.LISTINGS_PARSE
            pr.classification = Classification.SCRAPER_SELECTOR_DRIFT
            pr.evidence = evidence
            return pr, []

        # Passed layers 2-4.
        pr.healthy = True
        pr.job_count = len(listings)
        pr.evidence = evidence
        return pr, listings
    except Exception as e:
        # An unexpected error during navigation is treated as structure drift for
        # this preset (the page did not reach a scrapeable state).
        pr.failed_layer = Layer.RESULTS_CONTAINER
        pr.classification = Classification.URL_OR_STRUCTURE_DRIFT
        pr.evidence = {"attempted_url": preset.url, "exception": repr(e)[:300]}
        return pr, []
    finally:
        page.close()


def _earliest_layer(layers: list[Layer]) -> Layer:
    return min(layers, key=_LAYER_ORDER.index)


def _aggregate(
    preset_results: list[PresetResult], commit: str | None, scorer_ran: bool
) -> CanaryResult:
    healthy_presets = [p for p in preset_results if p.healthy]
    failed_presets = [p for p in preset_results if not p.healthy]

    if not failed_presets:
        note = "" if scorer_ran else " (scorer layer skipped)"
        return CanaryResult(
            classification=Classification.HEALTHY,
            healthy=True,
            escalate=False,
            summary=f"All {len(preset_results)} presets healthy through every layer{note}.",
            presets=preset_results,
            last_known_good_commit=commit,
        )

    failed_layers = [p.failed_layer for p in failed_presets if p.failed_layer]

    # Mixed outcome: some presets healthy with jobs, others failed. The shared
    # "software/USA" shape means a partial failure points at a preset fixture,
    # not the scraper. Treat as low-priority maintenance.
    if healthy_presets and any(p.job_count > 0 for p in healthy_presets):
        names = ", ".join(p.name for p in failed_presets)
        return CanaryResult(
            classification=Classification.CANARY_MAINTENANCE,
            healthy=False,
            escalate=True,
            summary=(
                f"{len(failed_presets)} preset(s) failed ({names}) while others returned "
                f"healthy results with jobs. Likely a preset URL/fixture issue, not scraper drift."
            ),
            presets=preset_results,
            last_known_good_commit=commit,
        )

    # All presets failed. If they share a layer it is systemic; otherwise key on
    # the earliest (most fundamental) failing layer.
    earliest = _earliest_layer(failed_layers)
    classification = LAYER_CLASSIFICATION[earliest]
    same = len(set(failed_layers)) == 1
    detail = "all presets" if same else f"earliest failing layer {earliest.value}"
    return CanaryResult(
        classification=classification,
        healthy=False,
        escalate=True,
        summary=f"Systemic failure: {detail} -> {classification.value}.",
        presets=preset_results,
        last_known_good_commit=commit,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the live pipeline canary")
    parser.add_argument("--cdp-url", help="Override the CDP URL from config")
    parser.add_argument(
        "--no-scorer", action="store_true", help="Skip layer 5 (no Claude call)"
    )
    parser.add_argument(
        "--container-selector",
        help="Override the results-container selector (for simulating layer-3 drift)",
    )
    parser.add_argument("--url", help="Run a single custom preset against this URL")
    parser.add_argument("--plugin", default="hiring_cafe", help="Plugin for --url")
    parser.add_argument("--name", default="custom", help="Name for --url preset")
    args = parser.parse_args()

    presets = None
    if args.url:
        presets = [Preset(name=args.name, plugin=args.plugin, url=args.url)]

    result = run_live_canary(
        presets=presets,
        cdp_url=args.cdp_url,
        run_scorer=not args.no_scorer,
        container_selector_override=args.container_selector,
    )
    print(result.to_json())
    sys.exit(0 if result.healthy else 1)


if __name__ == "__main__":
    main()
