import argparse
import sys
from datetime import datetime
from pathlib import Path

from models import (
    AIScorer,
    FailedResult,
    FilteredResult,
    JobBoardPlugin,
    JobListing,
    ScoredResult,
)
from config import (
    _select_profile_dir,
    load_config,
    load_dedup_config,
    load_prefilter,
    load_profile,
    load_scorer_config,
)
from dedup import DedupStore, _build_store_path
from dedup_reporting import write_dedup_report
from plugins.linkedin.linkedin import LinkedInPlugin
from plugins.indeed.indeed import IndeedPlugin
from plugins.hiring_cafe.hiring_cafe import HiringCafePlugin
from plugins.remotive.remotive import RemotivePlugin
from plugins.mock.mock import MockPlugin
from scorers.claude_browser.claude_browser import ClaudeBrowserScorer
from scorers.llama.llama import LlamaScorer
from scorers.mock.mock import MockScorer

PLUGINS: dict[str, type] = {
    "linkedin": LinkedInPlugin,
    "indeed": IndeedPlugin,
    "hiring_cafe": HiringCafePlugin,
    "remotive": RemotivePlugin,
    "mock": MockPlugin,
}


def scrape(profile_dir: Path, plugin_name: str = "linkedin") -> list[JobListing]:
    prefilter = load_prefilter(profile_dir)
    plugin_cls = PLUGINS[plugin_name]
    plugin = plugin_cls(
        exclude_companies=prefilter["exclude_companies"],
        exclude_title_keywords=prefilter["exclude_title_keywords"],
        filter_reposts=prefilter.get("filter_reposts", False),
        max_age_days=prefilter.get("max_age_days"),
    )
    return plugin.scrape()


def _build_scorer(scorer_name: str) -> AIScorer:
    scorer_config = load_scorer_config(scorer_name)
    if scorer_name == "llama":
        return LlamaScorer(**scorer_config)
    return ClaudeBrowserScorer(project_url=scorer_config.get("project_url"))


def score(
    jobs: list[JobListing],
    profile_dir: Path,
    scorer_name: str = "claude_browser",
) -> tuple[
    list[tuple[JobListing, ScoredResult]],
    list[tuple[JobListing, FilteredResult]],
    list[tuple[JobListing, FailedResult]],
]:
    profile = load_profile(profile_dir)
    scorer = _build_scorer(scorer_name)

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


def _escape_md_pipe(text: str) -> str:
    return text.replace("|", "&#124;")


def report(
    ranked: list[tuple[JobListing, ScoredResult]],
    filtered: list[tuple[JobListing, FilteredResult]],
    failed: list[tuple[JobListing, FailedResult]],
    output_path: Path,
    dedup_count: int = 0,
) -> None:
    lines: list[str] = [
        f"# Results: {len(ranked)} scored, {len(filtered)} filtered, {len(failed)} failed, {dedup_count} duplicates removed\n"
    ]
    for rank, (job, result) in enumerate(ranked, start=1):
        lines.append("---\n")
        lines.append(f"| # | Title | Fit | Link |")
        lines.append(f"|---|-------|-----|------|")
        lines.append(
            f"| {rank} | {_escape_md_pipe(job.title)} at {_escape_md_pipe(job.company)} | {result.score}/100 | [View]({job.url}) |"
        )
        lines.append(f"\n**Requirements Match:** {result.requirements_match}/100")
        lines.append(f"**Domain Match:** {result.domain_match}/100\n")
        lines.append(f"{result.reasoning}\n")
        lines.append(f"**Gaps:** {result.gaps}\n")
        hard = "\n".join(r.strip() for r in result.hard_requirements.split("|"))
        preferred = "\n".join(
            r.strip() for r in result.preferred_requirements.split("|")
        )
        lines.append(f"**Hard Requirements:**\n{hard}\n")
        lines.append(f"**Preferred Requirements:**\n{preferred}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    print(f"Report written to {output_path}")


def _print_score_result(job: JobListing, result: ScoredResult) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {job.title} at {job.company}")
    print(f"{'=' * 60}")
    print(f"  Score:              {result.score}/100")
    print(f"  Requirements Match: {result.requirements_match}/100")
    print(f"  Domain Match:       {result.domain_match}/100")
    print(f"  Reasoning:\n    {result.reasoning}")
    print(f"  Gaps:\n    {result.gaps}")
    hard = "\n    ".join(
        r.strip() for r in result.hard_requirements.split("|") if r.strip()
    )
    preferred = "\n    ".join(
        r.strip() for r in result.preferred_requirements.split("|") if r.strip()
    )
    print(f"  Hard Requirements:\n    {hard}")
    print(f"  Preferred Requirements:\n    {preferred}")
    print()


def _print_filtered_result(job: JobListing, result: FilteredResult) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {job.title} at {job.company}")
    print(f"{'=' * 60}")
    print(f"  Filtered out: {result.reason}")
    print()


def _print_failed_result(job: JobListing, result: FailedResult) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {job.title} at {job.company}")
    print(f"{'=' * 60}")
    print(f"  Scoring failed: {result.reason}")
    print()


def interactive_job_loop(profile_dir: Path, scorer_name: str, output_dir: Path) -> None:
    print("\n=== Interactive Job Scorer ===")
    print("Paste job details and get an instant score.")
    print("A consolidated report will be generated when you're done.\n")

    all_ranked: list[tuple[JobListing, ScoredResult]] = []
    all_filtered: list[tuple[JobListing, FilteredResult]] = []
    all_failed: list[tuple[JobListing, FailedResult]] = []

    while True:
        try:
            title = input("Job title: ").strip()
            if not title:
                print("Title is required. Press Ctrl+C to exit.\n")
                continue

            company = input("Company: ").strip()
            if not company:
                print("Company is required. Press Ctrl+C to exit.\n")
                continue

            print("\nPaste the full job description, then press Ctrl+D when done:")
            description_lines = sys.stdin.readlines()
            description = "".join(description_lines).strip()

            if not description:
                print("Description is empty. Try again.\n")
                continue

            job = JobListing(
                title=title,
                company=company,
                location="",
                url="",
                date_posted=datetime.now().strftime("%Y-%m-%d"),
                description=description,
            )

            print(f"\nScoring {title} at {company}...")
            ranked, filtered, failed = score(
                [job], profile_dir, scorer_name=scorer_name
            )

            for j, result in ranked:
                _print_score_result(j, result)
                all_ranked.append((j, result))
            for j, result in filtered:
                _print_filtered_result(j, result)
                all_filtered.append((j, result))
            for j, result in failed:
                _print_failed_result(j, result)
                all_failed.append((j, result))

        except EOFError:
            print("\nNo input received. Press Ctrl+C to exit.\n")
            continue

        answer = input("\nScore another job? (y/n): ").strip().lower()
        if answer != "y":
            break
        print()

    if not all_ranked and not all_filtered and not all_failed:
        print("No jobs were scored. Bye!")
        return

    all_ranked.sort(key=lambda x: x[1].score, reverse=True)
    date_str = datetime.now().strftime("%Y_%m_%d")
    report_path = output_dir / f"interactive_{date_str}.md"
    report(all_ranked, all_filtered, all_failed, report_path)
    print(
        f"\nSession complete: {len(all_ranked)} scored, {len(all_filtered)} filtered, {len(all_failed)} failed."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="AI job discovery engine")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/report.md"),
        help="Path to write the report (default: output/report.md)",
    )
    parser.add_argument("--no-dedup", action="store_true", help="Skip deduplication")
    parser.add_argument(
        "--clear-dedup",
        action="store_true",
        help="Clear the dedup store before running",
    )
    parser.add_argument(
        "--interactive-job-score",
        "-ijs",
        action="store_true",
        help="Interactively paste and score individual jobs without scraping",
    )
    args = parser.parse_args()

    if args.interactive_job_score:
        config = load_config()
        profile_dir = _select_profile_dir()
        interactive_job_loop(profile_dir, config["scorer"], args.output.parent)
        return

    config = load_config()
    profile_dir = _select_profile_dir()
    plugin_name = config.get("plugin", "linkedin")
    jobs = scrape(profile_dir, plugin_name=plugin_name)

    dedup_count = 0
    new_jobs_to_score = jobs
    if args.clear_dedup:
        Path(_build_store_path(profile_dir)).unlink(missing_ok=True)
    if not args.no_dedup:
        dedup_config = load_dedup_config()
        store = DedupStore(
            profile_dir,
            company_threshold=dedup_config.get("company_threshold", 50),
            title_threshold=dedup_config.get("title_threshold", 80),
            description_threshold=dedup_config.get("description_threshold", 95),
        )
        new_jobs_to_score, dedup_matches, elapsed = store.deduplicate(jobs, plugin_name)
        dedup_count = len(dedup_matches)
        print(
            f"Dedup: {dedup_count} duplicates removed, {len(new_jobs_to_score)} new jobs to score ({elapsed:.2f}s)"
        )
        if dedup_matches:
            dedup_report_path = Path(
                f"output/dedup_report_{plugin_name}_{profile_dir.name}_{datetime.now().strftime('%Y_%m_%d')}.html"
            )
            write_dedup_report(dedup_matches, dedup_report_path)
            print(f"Dedup report: {dedup_report_path}")

    ranked, filtered, failed = score(
        new_jobs_to_score, profile_dir, scorer_name=config["scorer"]
    )

    # Append plugin, profile name and today's date to the report name
    date_str = datetime.now().strftime("%Y_%m_%d")
    profile_name = profile_dir.name
    output_path = args.output
    if output_path.suffix == ".md":
        output_path = output_path.with_name(
            f"{output_path.stem}_{plugin_name}_{profile_name}_{date_str}{output_path.suffix}"
        )

    report(ranked, filtered, failed, output_path, dedup_count)

    # Commit scored and filtered jobs to store (not failed — they may succeed next run)
    if not args.no_dedup:
        store.commit(ranked, filtered, config["scorer"])
        print(f"Dedup: committed {len(ranked) + len(filtered)} jobs to store")


if __name__ == "__main__":
    main()
