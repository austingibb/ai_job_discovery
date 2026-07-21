from models import AIScorer, JobListing, ScoringResult, UserProfile
from scorers.parser import parse_response

# Matches the five MockPlugin jobs. Addresses cover the location resolver's
# cases: valid near a configured location, valid but far, unparseable, and null.
_HARDCODED_RESPONSE = """\
JOB_ID: 0
STATUS: SCORED
SCORE: 78
REQS_MATCH: 80
DOMAIN_MATCH: 60
REASONING: Strong backend and distributed systems alignment with the Payments Core role. The candidate's cloud infrastructure background covers the AWS and service reliability requirements, though payments domain experience is limited.
GAPS: No direct payment systems experience.
HARD_REQUIREMENTS: - 3-5 years of backend development experience
PREFERRED_REQUIREMENTS: - Experience with payment systems
ADDRESS: 5301 Ballard Ave NW, Seattle, WA 98107

JOB_ID: 1
STATUS: SCORED
SCORE: 85
REQS_MATCH: 88
DOMAIN_MATCH: 82
REASONING: Excellent fit for the control plane role. The candidate's distributed systems and cloud networking background matches Google Cloud's stack, and systems programming experience covers the Go/C++ requirement.
GAPS: No significant gaps identified
HARD_REQUIREMENTS: - 3+ years of experience | - Strong CS fundamentals | - Systems programming background
PREFERRED_REQUIREMENTS: None listed
ADDRESS: 1600 Amphitheatre Parkway, Mountain View, CA

JOB_ID: 2
STATUS: FILTERED
REASON: Requires 12+ years of experience with 5 years in staff+ leadership, exceeding the candidate's seniority range.

JOB_ID: 3
STATUS: SCORED
SCORE: 55
REQS_MATCH: 50
DOMAIN_MATCH: 65
REASONING: Backend portion of the stack aligns well, but the role demands 2+ years of professional React/TypeScript, which the candidate lacks. Product-focused full stack work is a departure from the candidate's infrastructure background.
GAPS: No professional React/TypeScript frontend experience.
HARD_REQUIREMENTS: - 2-4 years of experience | - 2+ years professional React/TypeScript
PREFERRED_REQUIREMENTS: None listed
ADDRESS: 123 Not A Real Street, Nowhereville, ZZ 00000

JOB_ID: 4
STATUS: SCORED
SCORE: 70
REQS_MATCH: 75
DOMAIN_MATCH: 55
REASONING: Go, AWS, and Kubernetes requirements match the candidate's backend experience directly. Billing and subscription systems are outside the candidate's domain, holding the domain score down.
GAPS: No billing or usage metering experience.
HARD_REQUIREMENTS: - 2-5 years of backend engineering experience
PREFERRED_REQUIREMENTS: - Familiarity with billing or subscription systems
ADDRESS: null
"""


class MockScorer(AIScorer):
    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        return parse_response(_HARDCODED_RESPONSE, jobs)
