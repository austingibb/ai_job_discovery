from models import AIScorer, JobListing, ScoringResult, UserProfile
from scorers.parser import parse_response

# Hardcoded scorer response for the five MockPlugin jobs (JOB_ID 0-4), in the
# exact format scorers/parser.py expects. Mixes SCORED and FILTERED so the
# pipeline exercises both ScoredResult and FilteredResult paths without a
# browser or live LLM. JOB_ID 2 (Principal Engineer) is filtered on a YOE rule.
_HARDCODED_RESPONSE = """\
JOB_ID: 0
STATUS: SCORED
SCORE: 82
REQS_MATCH: 85
DOMAIN_MATCH: 78
REASONING: Strong backend match. The candidate's distributed systems and payments-adjacent experience lines up well with the Payments Core team, and the Java/AWS/PostgreSQL stack overlaps the background. Domain match is solid given prior fintech exposure.
GAPS: Limited direct experience with banking-partner integrations.
HARD_REQUIREMENTS: - 3-5 years backend development | - Distributed systems experience
PREFERRED_REQUIREMENTS: - Payment systems experience | - API design

JOB_ID: 1
STATUS: SCORED
SCORE: 74
REQS_MATCH: 76
DOMAIN_MATCH: 70
REASONING: Good systems-programming fit for Google Cloud networking. Go and strong CS fundamentals align with the candidate's background, though the C++ and RPC-heavy control-plane work is a partial stretch.
GAPS: Less hands-on C++ and large-scale RPC infrastructure experience.
HARD_REQUIREMENTS: - 3+ years experience | - Strong CS fundamentals
PREFERRED_REQUIREMENTS: - C++ systems programming | - Networking control planes

JOB_ID: 2
STATUS: FILTERED
REASON: Requires 12+ years of experience with 5+ years in a staff-plus leadership role, exceeding the candidate's seniority rules.

JOB_ID: 3
STATUS: SCORED
SCORE: 88
REQS_MATCH: 90
DOMAIN_MATCH: 84
REASONING: Excellent full-stack alignment. React/TypeScript frontend plus Kotlin/PostgreSQL backend matches the candidate's end-to-end product experience, and the 2-4 year band fits well.
GAPS: No significant gaps identified.
HARD_REQUIREMENTS: - 2-4 years experience | - 2+ years React/TypeScript
PREFERRED_REQUIREMENTS: - End-to-end feature ownership | - UI craftsmanship

JOB_ID: 4
STATUS: SCORED
SCORE: 79
REQS_MATCH: 80
DOMAIN_MATCH: 75
REASONING: Solid billing-platform backend fit. Go with some Python on AWS and Kubernetes maps to the candidate's cloud backend experience, and the metering/invoicing domain is adjacent to prior payments work.
GAPS: Limited direct subscription-billing domain experience.
HARD_REQUIREMENTS: - 2-5 years backend engineering | - Go experience
PREFERRED_REQUIREMENTS: - Billing or subscription systems | - Kubernetes
"""


class MockScorer(AIScorer):
    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        return parse_response(_HARDCODED_RESPONSE, jobs)
