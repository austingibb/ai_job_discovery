import json
from pathlib import Path

from playwright.sync_api import Page

from models import JobListing

_CONFIG_PATH = Path(__file__).parent / "config.json"


class LinkedInPlugin:
    def __init__(
        self,
        exclude_companies: list[str] | None = None,
        exclude_title_keywords: list[str] | None = None,
    ) -> None:
        config = json.loads(_CONFIG_PATH.read_text())
        self.cdp_url: str = config["cdp_url"]
        self.num_pages: int = config.get("num_pages", 1)
        self.exclude_companies: set[str] = {c.lower() for c in (exclude_companies or [])}
        self.exclude_title_keywords: list[str] = [k.lower() for k in (exclude_title_keywords or [])]

    def scrape(self) -> list[JobListing]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            page = browser.contexts[0].new_page()

            try:
                page.goto("https://www.linkedin.com/jobs")
                page.wait_for_load_state("domcontentloaded")

                input("\nSet your LinkedIn search filters, then press Enter to scrape...")

                jobs = self._scrape_all_pages(page)
                return self._prefilter(jobs)
            finally:
                page.close()

    def _prefilter(self, stubs: list[JobListing]) -> list[JobListing]:
        """Drop stubs by company name or title keyword before fetching descriptions."""
        kept = []
        for stub in stubs:
            if stub.company.lower() in self.exclude_companies:
                print(f"  [prefilter] Skipping {stub.title} @ {stub.company} (excluded company)")
                continue
            title_lower = stub.title.lower()
            if any(kw in title_lower for kw in self.exclude_title_keywords):
                print(f"  [prefilter] Skipping {stub.title} @ {stub.company} (excluded title keyword)")
                continue
            kept.append(stub)
        print(f"Prefilter: {len(stubs) - len(kept)} dropped, {len(kept)} remaining.")
        return kept

    def _scrape_all_pages(self, page: Page) -> list[JobListing]:
        """Scrape jobs across num_pages pages, clicking Next between each."""
        print(f"Scraping page 1 of {self.num_pages}...")
        jobs = self._scrape_jobs(page)
        print(f"  Found {len(jobs)} jobs.")

        for p in range(2, self.num_pages + 1):
            next_btn = page.locator('[data-testid="pagination-controls-next-button-visible"]')
            if next_btn.count() == 0:
                print("  No more pages.")
                break
            next_btn.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)
            print(f"Scraping page {p} of {self.num_pages}...")
            new_jobs = self._scrape_jobs(page)
            print(f"  Found {len(new_jobs)} jobs.")
            jobs.extend(new_jobs)

        print(f"Total jobs collected: {len(jobs)}")
        return jobs

    def _scrape_jobs(self, page: Page) -> list[JobListing]:
        """Scrape job listings from the current search results page.

        Clicks each card to load the detail panel, extracts metadata from the
        card and the job ID + description from the detail panel.
        """
        # LinkedIn switched from job-card-component-ref-{id} componentkeys to UUIDs.
        # Filter to cards that contain a dismiss button to avoid footer elements.
        unclicked = page.locator(
            '[data-testid="lazy-column"] div[role="button"][componentkey]'
            ':has(button[aria-label$=" job"])'
        )
        total = unclicked.count()
        jobs = []

        for i in range(total):                                                                                     
            card = unclicked.first  

        for i in range(total):
            card = unclicked.first

            dismiss_label = (
                card.locator('[aria-label^="Dismiss "]').first.get_attribute("aria-label") or ""
            )
            title = dismiss_label.removeprefix("Dismiss ").removesuffix(" job")

            paragraphs = card.locator("p").all_inner_texts()
            company = paragraphs[1] if len(paragraphs) > 1 else ""
            location = paragraphs[2] if len(paragraphs) > 2 else ""
            date_posted = paragraphs[-1] if paragraphs else ""

            # Click the card to load the detail panel and get the job ID from the URL.
            card.click()
            page.wait_for_timeout(1000)

            current_url = page.url
            job_id = ""
            if "currentJobId=" in current_url:
                job_id = current_url.split("currentJobId=")[1].split("&")[0]
            url = f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else current_url

            # Read description from the detail panel.
            desc_locator = page.locator(
                '[componentkey^="JobDetails_AboutTheJob_"] [data-testid="expandable-text-box"]'
            )
            try:
                desc_locator.wait_for(state="visible", timeout=5_000)
                description = desc_locator.inner_text()
            except Exception:
                description = ""

            print(f"  [{i + 1}/{total}] {title} @ {company}")

            jobs.append(
                JobListing(
                    title=title,
                    company=company,
                    location=location,
                    url=url,
                    date_posted=date_posted,
                    description=description,
                )
            )

        return jobs
