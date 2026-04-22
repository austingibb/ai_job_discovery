from dataclasses import dataclass
from typing import Protocol


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
    def scrape(self) -> list[JobListing]: ...


class AIScorer(Protocol):
    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]: ...
