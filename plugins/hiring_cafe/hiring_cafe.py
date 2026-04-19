import json
import re
from pathlib import Path

from playwright.sync_api import Page

from models import JobListing

_CONFIG_PATH = Path(__file__).parent / "config.json"


class HiringCafePlugin:
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
        self.max_age_days: int | None = max_age_days

    def scrape(self) -> list[JobListing]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            page = browser.contexts[0].new_page()
            page.set_viewport_size({"width": 1920, "height": 1080})

            try:
                page.goto("https://hiring.cafe/")
                page.wait_for_load_state("domcontentloaded")

                input("\nSet your Hiring Cafe search filters, then press Enter to scrape...")

                jobs = self._scrape_all_pages(page)
                return self._prefilter(jobs)
            finally:
                page.close()

    @staticmethod
    def _parse_age_days(text: str) -> float | None:
        """Parse relative age text like '2mo', '3d', '1w' into days."""
        text = text.strip().lower()
        m = re.match(r"(\d+)\s*(mo|d|w|h)", text)
        if not m:
            return None
        n = int(m.group(1))
        unit = m.group(2)
        return {"h": n / 24, "d": float(n), "w": float(n * 7), "mo": float(n * 30)}[unit]

    def _prefilter(self, stubs: list[JobListing]) -> list[JobListing]:
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
        """Scrape jobs, navigating through pagination buttons."""
        print(f"Scraping page 1 of {self.num_pages}...")
        jobs = self._scrape_jobs(page)
        print(f"  Found {len(jobs)} jobs.")

        for pg in range(2, self.num_pages + 1):
            try:
                next_btn = page.locator('a[aria-label="Next page"]')
                if next_btn.count() == 0 or not next_btn.is_visible():
                    print("  No more pages available.")
                    break
                
                next_btn.click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)
                
                print(f"Scraping page {pg} of {self.num_pages}...")
                new_jobs = self._scrape_jobs(page)
                print(f"  Found {len(new_jobs)} new jobs.")
                jobs.extend(new_jobs)
            except Exception as e:
                print(f"  [error] Failed to navigate to page {pg}: {e}")
                break

        print(f"Total jobs collected: {len(jobs)}")
        return jobs

    def _scrape_jobs(self, page: Page) -> list[JobListing]:
        """Collect stubs from the card grid, then open each job in a new tab
        to get the full description."""

        # Phase 1: collect stubs from card grid.
        grid = page.locator("div.grid")
        cards = grid.locator("> div")
        total = cards.count()
        stubs: list[dict] = []
        seen_urls: set[str] = set()

        for i in range(total):
            card = cards.nth(i)

            viewjob_link = card.locator('a[href^="/viewjob/"]')
            if viewjob_link.count() == 0:
                continue
            try:
                href = viewjob_link.first.get_attribute("href", timeout=3_000) or ""
            except Exception as e:
                print(f"  [{i + 1}/{total}] Skipping (failed to get href: {e})")
                continue
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            title = ""
            try:
                # Title is in the div just after the div containing the age (first SVG)
                first_svg_parent = card.locator("svg >> nth=0").locator("xpath=..")
                title_div = first_svg_parent.locator("xpath=following-sibling::div[1]")
                title = title_div.locator("span").first.inner_text(timeout=3_000).strip()
            except Exception:
                pass
            if not title:
                continue

            company = ""
            try:
                company = card.locator("picture img").first.get_attribute("alt", timeout=3_000) or ""
            except Exception:
                pass

            date_posted = ""
            try:
                # Date is the span sibling of the first SVG in the card
                first_svg_sibling = card.locator("svg >> nth=0").locator("xpath=following-sibling::span").first
                age_text = first_svg_sibling.inner_text(timeout=3_000).strip()
                if age_text:
                    date_posted = f"{age_text} ago"
            except Exception:
                pass

            location = ""
            try:
                # Location is the span sibling of the second SVG in the card
                second_svg_sibling = card.locator("svg >> nth=1").locator("xpath=following-sibling::span").first
                location = second_svg_sibling.inner_text(timeout=3_000).strip()
            except Exception:
                pass

            stubs.append({
                "url": f"https://hiring.cafe{href}",
                "title": title,
                "company": company,
                "location": location,
                "date_posted": date_posted,
            })

        print(f"  Collected {len(stubs)} stubs, fetching descriptions...")

        # Phase 2: open each job in a new tab to get the description.
        context = page.context
        jobs: list[JobListing] = []
        tab = context.new_page()

        for idx, stub in enumerate(stubs, start=1):
            try:
                tab.goto(stub["url"])
                tab.wait_for_load_state("domcontentloaded")

                # Extract the external job posting URL from embedded Next.js data.
                page_content = tab.content()
                next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_content, re.DOTALL)
                if next_data_match:
                    try:
                        next_data = json.loads(next_data_match.group(1))
                        apply_url = next_data.get("props", {}).get("pageProps", {}).get("job", {}).get("apply_url")
                        if apply_url and apply_url.startswith("http"):
                            stub["url"] = apply_url
                    except json.JSONDecodeError:
                        pass

                desc_locator = tab.locator("article.prose")
                desc_locator.wait_for(state="visible", timeout=10_000)
                description = desc_locator.inner_text(timeout=10_000)
            except Exception as e:
                print(f"  [{idx}/{len(stubs)}] Skipping {stub['title']} @ {stub['company']} (failed to get description: {e})")
                continue

            print(f"  [{idx}/{len(stubs)}] {stub['title']} @ {stub['company']}")
            jobs.append(
                JobListing(
                    title=stub["title"],
                    company=stub["company"],
                    location=stub["location"],
                    url=stub["url"],
                    date_posted=stub["date_posted"],
                    description=description,
                )
            )
        tab.close()


        return jobs
