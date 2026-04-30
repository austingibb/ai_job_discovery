import json
import re
import time
from datetime import date
from pathlib import Path
from rapidfuzz import fuzz

from dataclasses import dataclass
from models import FilteredResult, JobListing, ScoredResult


@dataclass
class DedupMatch:
    """Details about why a job was flagged as a duplicate."""
    job: JobListing
    matched_company: str
    matched_title: str
    matched_description: str
    matched_url: str
    matched_first_seen: str
    company_score: float
    title_score: float
    description_score: float


DEFAULT_STORE_PATH = Path("data/seen_jobs.json")


def _build_store_path(profile_dir: Path) -> Path:
    """Build per-profile store path: data/seen_jobs_{profile_name}.json"""
    parent = profile_dir.parent.name
    name = profile_dir.name
    if parent == "profiles" and name != "default":
        return DEFAULT_STORE_PATH.parent / f"{DEFAULT_STORE_PATH.stem}_{name}.json"
    return DEFAULT_STORE_PATH

LEGAL_SUFFIXES = [
    "inc", "llc", "corp", "corporation", "ltd", "limited",
    "co", "company", "group", "technologies", "tech",
    "solutions", "holdings", "enterprises", "services",
]


def normalize_company(name: str) -> str:
    name = name.lower()
    for suffix in LEGAL_SUFFIXES:
        pattern = rf"{suffix}[.,]?\s*$"
        name = re.sub(pattern, "", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"\s+", " ", title)
    title = title.strip().strip(".,;:")
    return title

class DedupStore:
    def __init__(
        self,
        profile_dir: Path,
        company_threshold: float = 50,
        title_threshold: float = 80,
        description_threshold: int = 95,
    ):
        self.store_path = _build_store_path(profile_dir)
        self.company_threshold = company_threshold
        self.title_threshold = title_threshold
        self.description_threshold = description_threshold

    def load(self) -> dict:
        if not self.store_path.exists():
            return {}
        try:
            return json.loads(self.store_path.read_text())
        except (json.JSONDecodeError, OSError):
            print(f"Warning: Could not read {self.store_path}, starting fresh")
            return {}

    def save(self, store: dict) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(store, indent=2))

    def _find_candidates(
        self, job: JobListing, store: dict
    ) -> list[tuple[dict, float, float]]:
        """Find potential duplicate entries from the store.

        Two-stage filter:
        1. Company similarity (token_set_ratio) — loose threshold to catch
           "stripe" vs "stripe payments", "google cloud" vs "google"
        2. Title similarity (token_sort_ratio) — strict threshold to reject
           different roles at the same company like "SWE" vs "Principal Engineer"

        Both must pass before description comparison runs.

        Returns list of (stored_entry, company_score, title_score).
        """
        norm_company = normalize_company(job.company)
        norm_title = normalize_title(job.title)
        candidates = []

        for stored_entry in store.values():
            stored_norm_company = normalize_company(stored_entry["company"])

            # Fast path: exact company match avoids fuzzy scoring entirely
            if stored_norm_company == norm_company:
                company_score = 100.0
            else:
                company_score = fuzz.token_set_ratio(norm_company, stored_norm_company)

            if company_score < self.company_threshold:
                continue

            title_score = fuzz.token_sort_ratio(norm_title, normalize_title(stored_entry["title"]))
            if title_score < self.title_threshold:
                continue

            candidates.append((stored_entry, company_score, title_score))

        return candidates

    def deduplicate(
        self, jobs: list[JobListing], plugin_name: str
    ) -> tuple[list[JobListing], list[DedupMatch], float]:
        """Find duplicates without committing to store.

        Returns (new_jobs, duplicate_matches, elapsed_seconds).
        Each DedupMatch contains the new job, the matched stored job's details
        (including both descriptions), and the similarity scores.
        """
        start = time.perf_counter()

        store = self.load()
        new_jobs = []
        duplicate_matches: list[DedupMatch] = []

        for job in jobs:
            match: DedupMatch | None = None

            for candidate, company_score, title_score in self._find_candidates(job, store):
                desc_score = fuzz.ratio(job.description.lower(), candidate["description"].lower())
                if desc_score >= self.description_threshold:
                    match = DedupMatch(
                        job=job,
                        matched_company=candidate["company"],
                        matched_title=candidate["title"],
                        matched_description=candidate["description"],
                        matched_url=candidate.get("url", ""),
                        matched_first_seen=candidate.get("first_seen", ""),
                        company_score=company_score,
                        title_score=title_score,
                        description_score=desc_score,
                    )
                    break

            if match:
                duplicate_matches.append(match)
            else:
                new_jobs.append(job)

        elapsed = time.perf_counter() - start
        return new_jobs, duplicate_matches, elapsed

    def commit(
        self,
        scored: list[tuple[JobListing, ScoredResult]],
        filtered: list[tuple[JobListing, FilteredResult]],
        scorer_name: str,
    ) -> None:
        """Add scored and filtered jobs to the persistent store.

        Called after scoring completes so that only successfully scored or
        filtered jobs are stored as "seen". Failed jobs (scorer crashes, etc.)
        are not committed because they may succeed on the next run.

        Args:
            scored: list of (JobListing, ScoredResult) tuples
            filtered: list of (JobListing, FilteredResult) tuples
            scorer_name: name of the scorer used for scoring
        """
        store = self.load()

        for job, result in scored:
            fingerprint = f"{normalize_company(job.company)}|{normalize_title(job.title)}"
            store_key = fingerprint
            counter = 2
            while store_key in store:
                store_key = f"{fingerprint}#{counter}"
                counter += 1
            store[store_key] = {
                "company": job.company,
                "title": job.title,
                "url": job.url,
                "scorer": scorer_name,
                "first_seen": date.today().isoformat(),
                "description": job.description,
                "scoring_result_type": "scored",
                "result_reason": result.reasoning,
                "score": result.score,
                "requirements_match": result.requirements_match,
                "domain_match": result.domain_match,
                "gaps": result.gaps,
            }

        for job, result in filtered:
            fingerprint = f"{normalize_company(job.company)}|{normalize_title(job.title)}"
            store_key = fingerprint
            counter = 2
            while store_key in store:
                store_key = f"{fingerprint}#{counter}"
                counter += 1
            store[store_key] = {
                "company": job.company,
                "title": job.title,
                "url": job.url,
                "scorer": scorer_name,
                "first_seen": date.today().isoformat(),
                "description": job.description,
                "scoring_result_type": "filtered",
                "result_reason": result.reason,
                "score": -1,
            }

        self.save(store)
