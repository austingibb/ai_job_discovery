import json
import re
import time
from datetime import date
from pathlib import Path
from rapidfuzz import fuzz

from models import FilteredResult, JobListing, ScoredResult


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


def description_similar(desc_a: str, desc_b: str, threshold: int) -> bool:
    return fuzz.token_set_ratio(desc_a.lower(), desc_b.lower()) >= threshold


class DedupStore:
    def __init__(
        self,
        profile_dir: Path,
        company_threshold: float = 50,
        title_threshold: float = 80,
        description_threshold: int = 80,
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
    ) -> list[dict]:
        """Find potential duplicate entries from the store.

        Two-stage filter:
        1. Company similarity (token_set_ratio) — loose threshold to catch
           "stripe" vs "stripe payments", "google cloud" vs "google"
        2. Title similarity (token_sort_ratio) — strict threshold to reject
           different roles at the same company like "SWE" vs "Principal Engineer"

        Both must pass before description comparison runs.
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

            candidates.append(stored_entry)

        return candidates

    def deduplicate(
        self, jobs: list[JobListing], plugin_name: str
    ) -> tuple[list[JobListing], list[JobListing], float]:
        """Find duplicates without committing to store.

        Returns (new_jobs, duplicate_jobs, elapsed_seconds).
        New jobs are NOT added to the store yet — use commit() after scoring
        to persist them. This way only successfully scored/filtered jobs are
        stored, not failed ones.
        """
        start = time.perf_counter()

        store = self.load()
        new_jobs = []
        duplicate_jobs = []

        for job in jobs:
            is_duplicate = False

            for candidate in self._find_candidates(job, store):
                if description_similar(
                    job.description,
                    candidate["description"],
                    self.description_threshold,
                ):
                    is_duplicate = True
                    break

            if is_duplicate:
                duplicate_jobs.append(job)
            else:
                new_jobs.append(job)

        elapsed = time.perf_counter() - start
        return new_jobs, duplicate_jobs, elapsed

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
