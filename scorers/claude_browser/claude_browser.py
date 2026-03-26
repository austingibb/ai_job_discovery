import json
from pathlib import Path

from playwright.sync_api import Page

from models import FailedResult, JobListing, ScoringResult, ScoringError, UserProfile
from scorers.parser import parse_response
from scorers.prompt import build_prompt, build_continuation_prompt

_CONFIG_PATH = Path(__file__).parent / "config.json"


class ClaudeBrowserScorer:
    def __init__(self, project_url: str | None = None) -> None:
        config = json.loads(_CONFIG_PATH.read_text())
        self.cdp_url: str = config["cdp_url"]
        self.project_url: str = project_url or config["default_url"]
        self.batch_size: int = config["batch_size"]

    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        from playwright.sync_api import sync_playwright

        results: list[ScoringResult] = []

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            context = browser.contexts[0]
            page = context.new_page()

            try:
                page.goto(self.project_url)
                page.wait_for_load_state("networkidle")

                for i in range(0, len(jobs), self.batch_size):
                    batch = jobs[i : i + self.batch_size]
                    pct = round(i / len(jobs) * 100)
                    print(f"[{pct:3d}%] Scoring jobs {i + 1}–{min(i + len(batch), len(jobs))} of {len(jobs)}...")

                    if i == 0:
                        prompt = build_prompt(profile, batch, start_index=i)
                    else:
                        prompt = build_continuation_prompt(batch, start_index=i)

                    try:
                        response = self._send_message(page, prompt)
                        results.extend(parse_response(response, batch, start_index=i))
                    except Exception as e:
                        print(f"  [error] Batch failed, skipping {len(batch)} jobs: {e}")
                        results.extend(FailedResult(reason=str(e)) for _ in batch)

            finally:
                page.close()

        print("[100%] Scoring complete.")
        return results

    def _send_message(self, page: Page, prompt: str) -> str:
        editor = page.locator('div[contenteditable="true"][data-testid="chat-input"]').first
        editor.wait_for(state="visible")
        page.wait_for_timeout(1000)

        editor.click()
        editor.focus()

        inserted = page.evaluate(
            "(text) => document.execCommand('insertText', false, text)",
            prompt,
        )

        editor_text = editor.inner_text()
        prompt_preview = prompt[:80].replace("\n", " ")
        print(f"  [send] insertText returned {inserted}, editor length: {len(editor_text)} chars, prompt: \"{prompt_preview}...\"")

        if not inserted or len(editor_text.strip()) == 0:
            raise ScoringError(
                "Failed to insert prompt into editor",
                raw_response="",
            )

        page.keyboard.press("Enter")

        streaming = page.locator('[data-is-streaming="true"]')
        streaming.wait_for(state="attached", timeout=15_000)
        streaming.wait_for(state="detached", timeout=300_000)

        page.wait_for_timeout(1000)

        responses = page.locator('.standard-markdown')
        return responses.last.inner_text()
