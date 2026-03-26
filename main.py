import argparse
from pathlib import Path

from models import AIScorer, FilteredResult, JobBoardPlugin, JobListing, ScoredResult
from config import load_prefilter, load_profile, load_scorer_config
from plugins.linkedin.linkedin import LinkedInPlugin
from scorers.claude_browser.claude_browser import ClaudeBrowserScorer

# Phase 3: from scorers.claude_browser.claude_browser import ClaudeBrowserScorer
# Phase 4: from report import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(description="AI job discovery engine")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/report.md"),
        help="Path to write the report (default: output/report.md)",
    )
    args = parser.parse_args()

    profile = load_profile()
    prefilter = load_prefilter()

    plugin: JobBoardPlugin = LinkedInPlugin(
        exclude_companies=prefilter["exclude_companies"],
        exclude_title_keywords=prefilter["exclude_title_keywords"],
    )
    scorer_config = load_scorer_config("claude_browser")
    scorer: AIScorer = ClaudeBrowserScorer(project_url=scorer_config.get("project_url"))
    # Phase 3: scorer = ClaudeBrowserScorer()

    jobs: list[JobListing] = plugin.scrape()

    scored: list[tuple[JobListing, ScoredResult]] = []
    filtered: list[tuple[JobListing, FilteredResult]] = []

    for job, result in zip(jobs, scorer.score(profile, jobs)):
        if isinstance(result, FilteredResult):
            filtered.append((job, result))
        else:
            scored.append((job, result))

    ranked = sorted(scored, key=lambda x: x[1].score, reverse=True)

    # Phase 4: generate_report(ranked, filtered, output_path=args.output)
    lines: list[str] = [f"# Results: {len(ranked)} scored, {len(filtered)} filtered\n"]
    for job, result in ranked:
        lines.append("---\n")
        lines.append(f"| Title | Fit | Link |")
        lines.append(f"|-------|-----|------|")
        lines.append(f"| {job.title} at {job.company} | {result.score}/100 | [View]({job.url}) |")
        lines.append(f"\n{result.reasoning}\n")

    output = "\n".join(lines)
    args.output.write_text(output)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
