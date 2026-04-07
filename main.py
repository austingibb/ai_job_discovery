import argparse
from pathlib import Path

from models import FailedResult, FilteredResult, JobListing, ScoredResult
from config import _select_profile_dir, load_prefilter, load_profile, load_scorer_config
from plugins.linkedin.linkedin import LinkedInPlugin
from scorers.claude_browser.claude_browser import ClaudeBrowserScorer


def scrape(profile_dir: Path) -> list[JobListing]:
    prefilter = load_prefilter(profile_dir)
    plugin = LinkedInPlugin(
        exclude_companies=prefilter["exclude_companies"],
        exclude_title_keywords=prefilter["exclude_title_keywords"],
        filter_reposts=prefilter.get("filter_reposts", False),
        max_age_days=prefilter.get("max_age_days"),
    )
    return plugin.scrape()


def score(
    jobs: list[JobListing],
    profile_dir: Path,
) -> tuple[list[tuple[JobListing, ScoredResult]], list[tuple[JobListing, FilteredResult]], list[tuple[JobListing, FailedResult]]]:
    profile = load_profile(profile_dir)
    scorer_config = load_scorer_config("claude_browser", profile_dir)
    scorer = ClaudeBrowserScorer(project_url=scorer_config.get("project_url"))

    scored = []
    filtered = []
    failed = []
    for job, result in zip(jobs, scorer.score(profile, jobs)):
        if isinstance(result, FailedResult):
            failed.append((job, result))
        elif isinstance(result, FilteredResult):
            filtered.append((job, result))
        else:
            scored.append((job, result))
    return sorted(scored, key=lambda x: x[1].score, reverse=True), filtered, failed


def report(
    ranked: list[tuple[JobListing, ScoredResult]],
    filtered: list[tuple[JobListing, FilteredResult]],
    failed: list[tuple[JobListing, FailedResult]],
    output_path: Path,
) -> None:
    lines: list[str] = [f"# Results: {len(ranked)} scored, {len(filtered)} filtered, {len(failed)} failed\n"]
    for rank, (job, result) in enumerate(ranked, start=1):
        lines.append("---\n")
        lines.append(f"| # | Title | Fit | Link |")
        lines.append(f"|---|-------|-----|------|")
        lines.append(f"| {rank} | {job.title} at {job.company} | {result.score}/100 | [View]({job.url}) |")
        lines.append(f"\n{result.reasoning}\n")
        hard = "\n".join(r.strip() for r in result.hard_requirements.split("|"))
        preferred = "\n".join(r.strip() for r in result.preferred_requirements.split("|"))
        lines.append(f"**Hard Requirements:**\n{hard}\n")
        lines.append(f"**Preferred Requirements:**\n{preferred}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    print(f"Report written to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI job discovery engine")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/report.md"),
        help="Path to write the report (default: output/report.md)",
    )
    args = parser.parse_args()

    profile_dir = _select_profile_dir()
    jobs = scrape(profile_dir)
    ranked, filtered, failed = score(jobs, profile_dir)
    report(ranked, filtered, failed, args.output)


if __name__ == "__main__":
    main()
