import html
from pathlib import Path

from dedup import DedupMatch


def score_color(score: float) -> str:
    if score >= 90:
        return "#e74c3c"
    if score >= 80:
        return "#e67e22"
    return "#27ae60"


def html_escape(text: str) -> str:
    return html.escape(text)


def truncate_desc(desc: str, limit: int = 2000) -> str:
    if len(desc) <= limit:
        return desc
    return desc[:limit] + "..."


def write_dedup_report(matches: list[DedupMatch], output_path: Path) -> None:
    rows = []
    for i, m in enumerate(matches, 1):
        job = m.job
        rows.append(f"""
        <div class="match" id="match-{i}">
          <div class="match-header">
            <span class="match-num">#{i}</span>
            <strong>{html_escape(job.title)}</strong> at <strong>{html_escape(job.company)}</strong>
            {f'<a href="{html_escape(job.url)}">[link]</a>' if job.url else ""}
          </div>
          <div class="scores">
            <span>Company: <b style="color:{score_color(m.company_score)}">{m.company_score:.0f}</b></span>
            <span>Title: <b style="color:{score_color(m.title_score)}">{m.title_score:.0f}</b></span>
            <span>Description: <b style="color:{score_color(m.description_score)}">{m.description_score:.0f}</b></span>
          </div>
          <div class="side-by-side">
            <div class="col">
              <h3>New Job</h3>
              <p class="meta">{html_escape(job.title)} at {html_escape(job.company)}</p>
              <pre>{html_escape(job.description)}</pre>
            </div>
            <div class="col">
              <h3>Matched Stored Job</h3>
              <p class="meta">{html_escape(m.matched_title)} at {html_escape(m.matched_company)}
                {f" (first seen {m.matched_first_seen})" if m.matched_first_seen else ""}
                {f' <a href="{html_escape(m.matched_url)}">[link]</a>' if m.matched_url else ""}
              </p>
              <pre>{html_escape(m.matched_description)}</pre>
            </div>
          </div>
        </div>""")

    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Dedup Report</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 1400px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; }}
  .summary {{ background: #fff; padding: 12px 20px; border-radius: 8px; margin-bottom: 20px; }}
  .match {{ background: #fff; border-radius: 8px; margin-bottom: 24px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .match-header {{ font-size: 1.1em; margin-bottom: 8px; }}
  .match-num {{ background: #e74c3c; color: #fff; padding: 2px 8px; border-radius: 4px; margin-right: 8px; font-size: 0.85em; }}
  .scores {{ display: flex; gap: 24px; margin-bottom: 12px; padding: 8px 12px; background: #f9f9f9; border-radius: 4px; }}
  .scores span {{ font-size: 0.95em; }}
  .side-by-side {{ display: flex; gap: 16px; }}
  .col {{ flex: 1; min-width: 0; }}
  .col h3 {{ margin: 0 0 4px 0; font-size: 0.95em; color: #555; }}
  .col .meta {{ font-size: 0.85em; color: #777; margin: 0 0 8px 0; }}
  .col pre {{ white-space: pre-wrap; word-wrap: break-word; font-size: 0.8em; background: #fafafa; border: 1px solid #eee; padding: 12px; border-radius: 4px; max-height: 400px; overflow-y: auto; }}
  a {{ color: #3498db; }}
</style></head><body>
<h1>Dedup Report</h1>
<div class="summary">{len(matches)} jobs flagged as duplicates</div>
{"".join(rows)}
</body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content)
