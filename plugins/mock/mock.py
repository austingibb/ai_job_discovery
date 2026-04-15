from models import JobListing


class MockPlugin:
    def __init__(
        self,
        exclude_companies: list[str] | None = None,
        exclude_title_keywords: list[str] | None = None,
        filter_reposts: bool = False,
        max_age_days: int | None = None,
    ) -> None:
        pass

    def scrape(self) -> list[JobListing]:
        return [
            JobListing(
                title="Software Development Engineer II",
                company="Stripe",
                location="Seattle, WA",
                url="https://linkedin.com/jobs/view/100001",
                date_posted="2026-03-20",
                description=(
                    "We're looking for a Software Development Engineer to join our Payments Core team. "
                    "You'll build and maintain the distributed systems that process millions of payment "
                    "transactions daily. Our stack includes Java, AWS, and PostgreSQL. You'll work on API "
                    "design, service reliability, and cross-team integrations with banking partners. "
                    "3-5 years of experience in backend development required. Experience with payment "
                    "systems is a strong plus."
                ),
            ),
            JobListing(
                title="Software Engineer L4",
                company="Google",
                location="Mountain View, CA",
                url="https://linkedin.com/jobs/view/100002",
                date_posted="2026-03-22",
                description=(
                    "Join Google Cloud's networking team to build control plane services for our global "
                    "network infrastructure. You'll work in Go and C++ on distributed systems handling "
                    "millions of RPC calls per second. 3+ years of experience required. Strong CS "
                    "fundamentals and systems programming background needed."
                ),
            ),
            JobListing(
                title="Principal Engineer",
                company="Netflix",
                location="Los Gatos, CA",
                url="https://linkedin.com/jobs/view/100003",
                date_posted="2026-03-21",
                description=(
                    "We are seeking a Principal Engineer to define the technical strategy for our content "
                    "delivery platform. You will lead a team of 12 engineers, set architectural direction "
                    "across three orgs, and represent engineering in executive reviews. 12+ years of "
                    "software engineering experience required, with at least 5 years in a staff+ technical "
                    "leadership role. Deep expertise in large-scale distributed systems, CDNs, and video "
                    "streaming infrastructure."
                ),
            ),
            JobListing(
                title="Full Stack Engineer",
                company="Notion",
                location="San Francisco, CA (Hybrid)",
                url="https://linkedin.com/jobs/view/100004",
                date_posted="2026-03-23",
                description=(
                    "Build features across our entire stack — from React/TypeScript frontend to our Kotlin "
                    "and PostgreSQL backend. You'll own features end-to-end, from design through deployment. "
                    "We're looking for someone who loves crafting beautiful UI experiences and is equally "
                    "comfortable with backend API work. 2-4 years of experience. At least 2 years of "
                    "professional React/TypeScript experience required."
                ),
            ),
            JobListing(
                title="Backend Engineer, Billing Platform",
                company="Datadog",
                location="Remote (US)",
                url="https://linkedin.com/jobs/view/100005",
                date_posted="2026-03-24",
                description=(
                    "Join Datadog's billing platform team to build the systems that handle usage metering, "
                    "invoicing, and payment processing for our enterprise customers. You'll work primarily "
                    "in Go with some Python, using AWS services (SQS, DynamoDB, Lambda) and Kubernetes. "
                    "2-5 years of backend engineering experience. Familiarity with billing or subscription "
                    "systems is a big plus."
                ),
            ),
        ]
