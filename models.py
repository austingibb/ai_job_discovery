import os
from dataclasses import dataclass
from typing import Protocol

os.environ.setdefault("NODE_NO_WARNINGS", "1")


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    url: str
    date_posted: str
    description: str


@dataclass
class UserProfile:
    background: str
    rules: str
    fit_criteria: str
    request_address: bool = False  # ask the scorer for job addresses (profile has locations.json)


@dataclass
class FilteredResult:
    reason: str


@dataclass
class ScoredResult:
    score: int  # 0-100
    requirements_match: int  # 0-100
    domain_match: int  # 0-100
    reasoning: str
    gaps: str
    hard_requirements: str
    preferred_requirements: str
    address: str | None = None  # on-site street address, None if remote/unknown
    location_tier: int | None = None  # 1-3, None when location stage is skipped
    location_note: str = ""


@dataclass
class FailedResult:
    reason: str


ScoringResult = FilteredResult | ScoredResult | FailedResult


class ScoringError(Exception):
    """Raised when a scorer cannot parse or produce a valid response."""

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class JobBoardPlugin(Protocol):
    def gather_jobs(self) -> list[JobListing]: ...


class AIScorer(Protocol):
    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]: ...
