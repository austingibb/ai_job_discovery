import json
import re
import random
import time
from pathlib import Path

from playwright.sync_api import Page, Browser

from models import JobListing

_CONFIG_PATH = Path(__file__).parent / "config.json"


class RemotivePlugin:
    def __init__(
        self,
        exclude_companies: list[str] | None = None,
        exclude_title_keywords: list[str] | None = None,
        max_age_days: int | None = None,
        filter_reposts: bool = False,
    ) -> None:
        config = json.loads(_CONFIG_PATH.read_text())
        self.cdp_url: str = config["cdp_url"]
        self.num_groups: int = config.get("num_groups", 1)
        self.exclude_companies: set[str] = {c.lower() for c in (exclude_companies or [])}
        self.exclude_title_keywords: list[str] = [k.lower() for k in (exclude_title_keywords or [])]
        self.max_age_days: int | None = max_age_days

    def scrape(self) -> list[JobListing]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            page = browser.contexts[0].new_page()

            try:
                page.goto("https://remotive.com/remote-jobs")
                page.wait_for_load_state("domcontentloaded")

                input("\nSet your Remotive search filters, then press Enter to scrape...")

                jobs = self._scrape_all_groups(browser, page)
                return self._prefilter(jobs)
            finally:
                page.close()

    def _prefilter(self, jobs: list[JobListing]) -> list[JobListing]:
        kept = []
        for job in jobs:
            if job.company.lower() in self.exclude_companies:
                continue
            if any(kw in job.title.lower() for kw in self.exclude_title_keywords):
                continue
            # date_posted is usually "YYYY-MM-DD HH:MM:SS" in remotive data attributes
            # but it might be simplified.
            kept.append(job)
        return kept

    def _scrape_all_groups(self, browser: Browser, page: Page) -> list[JobListing]:
        all_jobs = []
        seen_job_ids = set()

        # Wait for the search results to actually load (stats element appears)
        try:
            page.wait_for_selector("#stats", state="visible", timeout=10000)
        except Exception as e:
            print(f"Warning: Stats element not found within timeout: {e}")

        for group_idx in range(1, self.num_groups + 1):
            print(f"Processing group {group_idx} of {self.num_groups}...")
            
            stubs = self._gather_stubs(page, seen_job_ids)
            print(f"  Found {len(stubs)} new stubs.")

            detail_page = browser.contexts[0].new_page()
            for stub in stubs:
                # Random wait to avoid rate limiting (2-7 seconds)
                time.sleep(random.uniform(1, 3))
                job = self._extract_details(detail_page, stub)
                if job:
                    all_jobs.append(job)
                seen_job_ids.add(stub["job_id"])

            detail_page.close()

            # Load more jobs
            more_btn = page.locator("#morejobs button")
            if more_btn.count() == 0:
                print("  No 'More Jobs' button found. Stopping.")
                break
            
            more_btn.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

        print(f"Total jobs collected: {len(all_jobs)}")
        return all_jobs

    def _gather_stubs(self, page: Page, seen_job_ids: set[str]) -> list[dict]:
        # Use the apply button to get metadata
        buttons = page.locator("button.job-apply-btn--list")
        total = buttons.count()
        stubs = []

        for i in range(total):
            btn = buttons.nth(i)
            job_id = btn.get_attribute("data-job-id")
            if not job_id or job_id in seen_job_ids:
                continue
            
            stubs.append({
                "job_id": job_id,
                "title": btn.get_attribute("data-job-title") or "",
                "company": btn.get_attribute("data-company-name") or "",
                "location": btn.get_attribute("data-location") or "",
                "date_posted": btn.get_attribute("data-publication-date") or "",
                "remotive_url": btn.get_attribute("data-job-url") or "",
            })
        
        return stubs

    def _extract_details(self, detail_page: Page, stub: dict) -> JobListing | None:
        try:
            # remotive_url might be relative or absolute
            url = stub["remotive_url"]
            if not url.startswith("http"):
                url = f"https://remotive.com{url}"
            
            detail_page.goto(url)
            detail_page.wait_for_load_state("domcontentloaded")

            # 1. Extract actual external URL
            apply_link = detail_page.locator("a.remotive-btn-chocolate:not(.job-tile-apply)").filter(
                has_text="Apply for this position",
            ).first
            actual_url = apply_link.get_attribute("href") if apply_link.count() > 0 else url

            # 2. Extract description
            # The description is under the "Role Description" header.
            # We can look for the text "Role Description" and get the subsequent paragraphs.
            # The provided HTML shows <p class="h2 tw-mt-4 remotive-text-bigger">Role Description</p>
            
            # We use a locator that finds the header and then we can traverse or just get the inner_text
            # of the container if it's structured.
            # Based on HTML: <div class="left"> contains the description.
            desc_container = detail_page.locator(".left")
            if desc_container.count() > 0:
                description = desc_container.first.inner_text()
            else:
                description = ""

            print(f"  Extracted {stub['title']} @ {stub['company']}")
            
            return JobListing(
                title=stub["title"],
                company=stub["company"],
                location=stub["location"],
                url=actual_url or url,
                date_posted=stub["date_posted"],
                description=description,
            )
        except Exception as e:
            print(f"  Error extracting details for {stub['job_id']}: {e}")
            return None
