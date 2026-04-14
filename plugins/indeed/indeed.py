import json
import re
from pathlib import Path

from playwright.sync_api import Page

from models import JobListing

_CONFIG_PATH = Path(__file__).parent / "config.json"


class IndeedPlugin:
    def __init__(
        self,
        exclude_companies: list[str] | None = None,
        exclude_title_keywords: list[str] | None = None,
        filter_reposts: bool = False,
        max_age_days: int | None = None,
    ) -> None:
        config = json.loads(_CONFIG_PATH.read_text())
        self.cdp_url: str = config["cdp_url"]
        self.num_pages: int = config.get("num_pages", 1)
        self.exclude_companies: set[str] = {c.lower() for c in (exclude_companies or [])}
        self.exclude_title_keywords: list[str] = [k.lower() for k in (exclude_title_keywords or [])]
        self.filter_reposts: bool = filter_reposts
        self.max_age_days: int | None = max_age_days

    def scrape(self) -> list[JobListing]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            page = browser.contexts[0].new_page()

            try:
                page.goto("https://www.indeed.com/jobs")
                page.wait_for_load_state("domcontentloaded")

                input("\nSet your Indeed search filters, then press Enter to scrape...")

                jobs = self._scrape_all_pages(page)
                return self._prefilter(jobs)
            finally:
                page.close()

    @staticmethod
    def _parse_age_days(text: str) -> float | None:
        """Parse Indeed age text like '3 days ago' or 'Just posted' into days."""
        if "just posted" in text.lower() or "today" in text.lower():
            return 0.0
        m = re.search(r"(\d+)\s+(hour|day|week|month)", text, re.IGNORECASE)
        if not m:
            return None
        n = int(m.group(1))
        unit = m.group(2).lower()
        return {"hour": n / 24, "day": float(n), "week": float(n * 7), "month": float(n * 30)}[unit]

    def _prefilter(self, stubs: list[JobListing]) -> list[JobListing]:
        """Drop stubs by company, title keyword, repost status, or age."""
        kept = []
        for stub in stubs:
            if stub.company.lower() in self.exclude_companies:
                print(f"  [prefilter] Skipping {stub.title} @ {stub.company} (excluded company)")
                continue
            title_lower = stub.title.lower()
            if any(kw in title_lower for kw in self.exclude_title_keywords):
                print(f"  [prefilter] Skipping {stub.title} @ {stub.company} (excluded title keyword)")
                continue
            if self.max_age_days is not None and stub.date_posted:
                age_days = self._parse_age_days(stub.date_posted)
                if age_days is not None and age_days > self.max_age_days:
                    print(f"  [prefilter] Skipping {stub.title} @ {stub.company} ({age_days:.1f}d old)")
                    continue
            kept.append(stub)
        print(f"Prefilter: {len(stubs) - len(kept)} dropped, {len(kept)} remaining.")
        return kept

    def _scrape_all_pages(self, page: Page) -> list[JobListing]:
        """Scrape jobs across num_pages pages, clicking Next between each."""
        print(f"Scraping page 1 of {self.num_pages}...")
        jobs = self._scrape_jobs(page)
        print(f"  Found {len(jobs)} jobs.")

        for pg in range(2, self.num_pages + 1):
            next_btn = page.locator('[data-testid="pagination-page-next"]')
            if next_btn.count() == 0:
                print("  No more pages.")
                break
            next_btn.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)
            print(f"Scraping page {pg} of {self.num_pages}...")
            new_jobs = self._scrape_jobs(page)
            print(f"  Found {len(new_jobs)} jobs.")
            jobs.extend(new_jobs)

        print(f"Total jobs collected: {len(jobs)}")
        return jobs

    def _scrape_jobs(self, page: Page) -> list[JobListing]:
        """Scrape job listings from the current Indeed search results page.

        Clicks each job card to load the description in the right pane,
        then extracts metadata and the full job description.
        """
        # Indeed job cards are <div> elements with class "cardOutline" and "result"
        # that also have an id starting with "job_" or contain a data-jk attribute.
        # We target the clickable job title links within the card list.
        card_locator = page.locator(
            '#mosaic-provider-jobcards .result .jobTitle a.jcs-JobTitle'
        )
        total = card_locator.count()
        jobs = []
        seen_keys: set[str] = set()

        for i in range(total):
            card = card_locator.nth(i)

            # Skip hidden duplicate cards (aria-hidden="true" on ancestor .cardOutline).
            card_outline = card.locator("xpath=ancestor::div[contains(@class, 'cardOutline')]").first
            if card_outline.get_attribute("aria-hidden") == "true":
                continue

            # Deduplicate by job key.
            jk = card.get_attribute("data-jk") or ""
            if jk and jk in seen_keys:
                continue
            if jk:
                seen_keys.add(jk)

            # Extract title from the span within the link.
            title = card.locator("span").first.inner_text().strip()

            # Navigate up to the result container to get company/location/salary.
            # The result container is the ancestor with class "result".
            result_container = card.locator("xpath=ancestor::div[contains(@class, 'result')]").first

            company = ""
            try:
                company = result_container.locator('[data-testid="company-name"]').first.inner_text().strip()
            except Exception:
                pass

            location = ""
            try:
                location = result_container.locator('[data-testid="text-location"]').first.inner_text().strip()
            except Exception:
                pass

            # Click the card to load the job description in the right pane.
            card.click()
            page.wait_for_timeout(1500)

            # Extract the job URL. Indeed updates the URL or we can read it from
            # the data-jk attribute on the card link.
            job_key = card.get_attribute("data-jk") or ""
            if job_key:
                url = f"https://www.indeed.com/viewjob?jk={job_key}"
            else:
                url = page.url

            date_posted = ""

            # Read the full job description from the right-side detail pane.
            description = ""
            desc_locator = page.locator('#jobDescriptionText')
            try:
                desc_locator.wait_for(state="visible", timeout=5_000)
                description = desc_locator.inner_text()
            except Exception:
                pass

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
