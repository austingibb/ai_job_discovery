from models import AIScorer, JobListing, ScoringResult, UserProfile


class MockScorer(AIScorer):
    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        return parse_response(_HARDCODED_RESPONSE, jobs)
