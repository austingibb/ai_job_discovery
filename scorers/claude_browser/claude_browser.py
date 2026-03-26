import json
from pathlib import Path

from models import JobListing, ScoringResult, ScoringError, UserProfile
from scorers.parser import parse_response
from scorers.prompt import build_prompt

_CONFIG_PATH = Path(__file__).parent / "config.json"


class ClaudeBrowserScorer:
    def __init__(self, project_url: str | None = None) -> None:
        config = json.loads(_CONFIG_PATH.read_text())
        self.cdp_url: str = config["cdp_url"]
        self.project_url: str = project_url or config["default_url"]
        self.batch_size: int = config["batch_size"]

    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        results: list[ScoringResult] = []
        for i in range(0, len(jobs), self.batch_size):
            batch = jobs[i : i + self.batch_size]
            pct = round(i / len(jobs) * 100)
            print(f"[{pct:3d}%] Scoring jobs {i + 1}–{min(i + len(batch), len(jobs))} of {len(jobs)}...")
            prompt = build_prompt(profile, batch, start_index=i)
            response = self._call_claude(prompt)
            results.extend(parse_response(response, batch, start_index=i))
        print("[100%] Scoring complete.")
        return results

    def _call_claude(self, prompt: str) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            context = browser.contexts[0]
            page = context.new_page()

            try:
                # Navigate to project — opens a new chat within the project context
                page.goto(self.project_url)
                page.wait_for_load_state("networkidle")

                # Fill the ProseMirror editor via execCommand (reliable with rich text editors)
                editor = page.locator('div[contenteditable="true"].ProseMirror').first
                editor.wait_for(state="visible")
                editor.click()
                page.evaluate(
                    "(text) => document.execCommand('insertText', false, text)",
                    prompt,
                )

                # Submit — Claude.ai sends on Enter
                page.keyboard.press("Enter")

                # Wait for streaming to start then finish
                streaming = page.locator('[data-is-streaming="true"]')
                streaming.wait_for(state="attached", timeout=15_000)
                streaming.wait_for(state="detached", timeout=300_000)

                # Extract the last assistant response
                responses = page.locator('.standard-markdown')
                return responses.last.inner_text()

            finally:
                page.close()
