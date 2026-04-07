from models import JobListing, ScoringResult, UserProfile
from scorers.parser import parse_response

_HARDCODED_RESPONSE = """\
JOB_ID: 0
STATUS: SCORED
SCORE: 95
REASONING: Strong match. The role is a React/TypeScript frontend position building customer-facing dashboards — closely aligned with the candidate's agency and e-commerce experience. The 1-3 year requirement fits well and the Next.js stack is a direct overlap.
HARD_REQUIREMENTS: - 1-3 years React/TypeScript experience | - Bachelor's in CS or related field
PREFERRED_REQUIREMENTS: - Next.js experience | - E-commerce domain knowledge

JOB_ID: 1
STATUS: FILTERED
REASON: Rule 1 — requires 5+ years of frontend experience, exceeding the candidate's threshold.

JOB_ID: 2
STATUS: FILTERED
REASON: Rule 3 — this is a pure DevOps/SRE role with no frontend component.

JOB_ID: 3
STATUS: SCORED
SCORE: 35
REASONING: The role is primarily backend microservices in Go with only a thin React admin panel. The candidate's backend exposure is limited to non-production Node.js work, making this a stretch.
HARD_REQUIREMENTS: - 3+ years Go experience | - Microservices architecture experience
PREFERRED_REQUIREMENTS: - React experience | - Kubernetes familiarity

JOB_ID: 4
STATUS: SCORED
SCORE: 88
REASONING: Full-stack role but heavily frontend-leaning. React and TypeScript are the primary technologies, with light Express API work that matches the candidate's existing Node.js exposure. The e-commerce domain aligns with prior ShopLocal experience.
HARD_REQUIREMENTS: - 2+ years React and TypeScript | - Experience with REST APIs
PREFERRED_REQUIREMENTS: - E-commerce experience | - Express.js knowledge\
"""


class MockScorer:
    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        return parse_response(_HARDCODED_RESPONSE, jobs)
