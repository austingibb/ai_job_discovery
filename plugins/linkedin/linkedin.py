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
            context = browser.contexts[0]
            page = context.new_page()

            try:
                page.goto("https://www.linkedin.com/jobs")
                page.wait_for_load_state("domcontentloaded")

                input("\nSet your LinkedIn search filters, then press Enter to scrape...")

                stubs = self._scrape_all_pages(page)
                stubs = self._prefilter(stubs)
                return self._fetch_descriptions(context, stubs)
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
        """Scrape stubs across num_pages pages, clicking Next between each."""
        print(f"Scraping page 1 of {self.num_pages}...")
        stubs = self._scrape_stubs(page)
        print(f"  Found {len(stubs)} jobs.")

        for p in range(2, self.num_pages + 1):
            next_btn = page.locator('[data-testid="pagination-controls-next-button-visible"]')
            if next_btn.count() == 0:
                print("  No more pages.")
                break
            next_btn.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)
            print(f"Scraping page {p} of {self.num_pages}...")
            new_stubs = self._scrape_stubs(page)
            print(f"  Found {len(new_stubs)} jobs.")
            stubs.extend(new_stubs)

        print(f"Total stubs collected: {len(stubs)}")
        return stubs

    def _scrape_stubs(self, page: Page) -> list[JobListing]:
        """Scrape title/company/location/url/date from the current search results page."""
        cards = page.locator('[role="button"][componentkey^="job-card-component-ref-"]')
        stubs = []

        for i in range(cards.count()):
            card = cards.nth(i)

            componentkey = card.get_attribute("componentkey") or ""
            job_id = componentkey.removeprefix("job-card-component-ref-")
            url = f"https://www.linkedin.com/jobs/view/{job_id}/"

            dismiss_label = (
                card.locator('[aria-label^="Dismiss "]').first.get_attribute("aria-label") or ""
            )
            title = dismiss_label.removeprefix("Dismiss ").removesuffix(" job")

            paragraphs = card.locator("p").all_inner_texts()
            company = paragraphs[1] if len(paragraphs) > 1 else ""
            location = paragraphs[2] if len(paragraphs) > 2 else ""
            date_posted = paragraphs[-1] if paragraphs else ""

            stubs.append(
                JobListing(
                    title=title,
                    company=company,
                    location=location,
                    url=url,
                    date_posted=date_posted,
                    description="",
                )
            )

        return stubs

    def _fetch_descriptions(self, context, stubs: list[JobListing]) -> list[JobListing]:
        """Open each job URL and extract the 'About the job' description."""
        detail_page = context.new_page()
        jobs = []

        total = len(stubs)
        try:
            for idx, stub in enumerate(stubs, start=1):
                print(f"[{idx}/{total}] Fetching description: {stub.title} @ {stub.company}")
                detail_page.goto(stub.url)
                detail_page.wait_for_load_state("domcontentloaded")

                # The "About the job" section has a stable componentkey prefix.
                # Scope the expandable text box to that container to avoid picking up
                # company description spans that share the same data-testid.
                desc_locator = detail_page.locator(
                    '[componentkey^="JobDetails_AboutTheJob_"] [data-testid="expandable-text-box"]'
                )
                desc_locator.wait_for(state="visible", timeout=10_000)
                description = desc_locator.inner_text()
                detail_page.wait_for_timeout(2000)

                jobs.append(
                    JobListing(
                        title=stub.title,
                        company=stub.company,
                        location=stub.location,
                        url=stub.url,
                        date_posted=stub.date_posted,
                        description=description,
                    )
                )
        finally:
            detail_page.close()

        return jobs
