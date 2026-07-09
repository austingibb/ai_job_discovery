"""Mock canary (3a): the core pipeline through the mock plugin and mock scorer.

Pure pytest, no browser and no live LLM. Validates the parts of the pipeline that
are independent of any site or model: scrape (mock), dedup, scoring/parsing, and
report generation. This is a useful standalone regression test regardless of the
rest of the canary/triage project.

Run from the repo root:  python -m pytest tests/test_mock_canary.py
"""

from pathlib import Path

from dedup import DedupStore
from main import report
from models import (
    FailedResult,
    FilteredResult,
    ScoredResult,
    ScoringResult,
    UserProfile,
)
from plugins.mock.mock import MockPlugin
from scorers.mock.mock import MockScorer

PROFILE = UserProfile(background="bg", rules="rules", fit_criteria="fit")


def _split(jobs, results):
    """Mirror main.score's split of results into ranked/filtered/failed."""
    ranked, filtered, failed = [], [], []
    for job, result in zip(jobs, results):
        if isinstance(result, FailedResult):
            failed.append((job, result))
        elif isinstance(result, FilteredResult):
            filtered.append((job, result))
        else:
            ranked.append((job, result))
    ranked.sort(key=lambda x: x[1].score, reverse=True)
    return ranked, filtered, failed


def test_mock_scorer_results_conform_to_scoring_result():
    jobs = MockPlugin().gather_jobs()
    results = MockScorer().score(PROFILE, jobs)

    assert len(results) == len(jobs)
    for result in results:
        assert isinstance(result, (FilteredResult, ScoredResult, FailedResult))
        # ScoringResult is the union of those three.
        assert isinstance(result, ScoringResult.__args__)

    scored = [r for r in results if isinstance(r, ScoredResult)]
    assert scored, "expected at least one scored result from the mock"
    for r in scored:
        assert 0 <= r.score <= 100
        assert 0 <= r.requirements_match <= 100
        assert 0 <= r.domain_match <= 100
        assert r.reasoning.strip()

    filtered = [r for r in results if isinstance(r, FilteredResult)]
    for r in filtered:
        assert r.reason.strip()


def test_mock_pipeline_produces_structured_report(tmp_path):
    jobs = MockPlugin().gather_jobs()
    results = MockScorer().score(PROFILE, jobs)
    ranked, filtered, failed = _split(jobs, results)

    out = tmp_path / "report.md"
    report(ranked, filtered, failed, out, dedup_count=0)

    # report() may suffix the name to avoid clobbering; find what it wrote.
    written = list(tmp_path.glob("report*.md"))
    assert len(written) == 1
    text = written[0].read_text()

    assert text.startswith(
        f"# Results: {len(ranked)} scored, {len(filtered)} filtered, "
        f"{len(failed)} failed, 0 duplicates removed"
    )
    # Every ranked job appears with a View link, in descending score order.
    scores_in_order = [r.score for _, r in ranked]
    assert scores_in_order == sorted(scores_in_order, reverse=True)
    for job, _ in ranked:
        assert job.title in text
        assert "[View](" in text


def test_mock_pipeline_dedup_round_trip(tmp_path):
    jobs = MockPlugin().gather_jobs()
    results = MockScorer().score(PROFILE, jobs)
    ranked, filtered, _ = _split(jobs, results)

    store = DedupStore(profile_dir=tmp_path)
    store.store_path = tmp_path / "seen_jobs.json"  # isolate from the repo's data/

    # First pass: nothing seen yet, so every job is new.
    new_jobs, matches, _ = store.deduplicate(jobs, "mock")
    assert len(new_jobs) == len(jobs)
    assert matches == []

    # Commit the scored + filtered jobs, then re-run: they should all be caught
    # as duplicates (identical company/title/description).
    store.commit(ranked, filtered, "mock")
    new_jobs2, matches2, _ = store.deduplicate(jobs, "mock")
    committed = len(ranked) + len(filtered)
    assert len(matches2) == committed
    assert len(new_jobs2) == len(jobs) - committed
