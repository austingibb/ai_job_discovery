import asyncio
import json
from pathlib import Path

from playwright.async_api import Page, async_playwright

from models import FailedResult, JobListing, ScoringResult, ScoringError, UserProfile
from scorers.parser import parse_response
from scorers.prompt import build_prompt, build_continuation_prompt

_CONFIG_PATH = Path(__file__).parent / "config.json"


class Progress:
    def __init__(self, total: int):
        self.total = total
        self.completed = 0

    def increment(self, count: int):
        self.completed += count


class ClaudeBrowserScorer:
    def __init__(self, project_url: str | None = None) -> None:
        config = json.loads(_CONFIG_PATH.read_text())
        self.cdp_url: str = config["cdp_url"]
        self.project_url: str = project_url or config["default_url"]
        self.batch_size: int = config["batch_size"]
        self.concurrency: int = config.get("concurrency", 1)

    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        return asyncio.run(self._score_async(profile, jobs))

    async def _score_async(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        results_map: dict[int, ScoringResult] = {}
        progress = Progress(len(jobs))

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(self.cdp_url)
            context = browser.contexts[0]

            # Start progress logger
            logger_task = asyncio.create_task(self._log_progress(progress))

            # Split jobs into batches
            batch_indices = [i for i in range(0, len(jobs), self.batch_size)]
            
            # Divide batches among workers
            workers = []
            for w_id in range(self.concurrency):
                worker_batches = batch_indices[w_id::self.concurrency]
                if worker_batches:
                    workers.append(self._process_worker(w_id, profile, jobs, worker_batches, context, progress))

            # Run workers in parallel
            worker_results = await asyncio.gather(*workers)
            for res in worker_results:
                results_map.update(res)

            logger_task.cancel()

        # Reassemble results in order
        final_results = []
        for i in range(len(jobs)):
            if i in results_map:
                final_results.append(results_map[i])
            else:
                final_results.append(FailedResult(reason="Result missing from worker"))

        print("[100%] Scoring complete.")
        return final_results

    async def _log_progress(self, progress: Progress):
        last_pct = -1
        try:
            while True:
                pct = round((progress.completed / progress.total) * 100) if progress.total > 0 else 100
                if pct > last_pct:
                    print(f"[{pct:3d}%] Completed {progress.completed}/{progress.total} jobs...")
                    last_pct = pct
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    async def _process_worker(
        self, worker_id: int, profile: UserProfile, jobs: list[JobListing], batch_indices: list[int], context, progress: Progress
    ) -> dict[int, ScoringResult]:
        page = await context.new_page()
        results: dict[int, ScoringResult] = {}

        try:
            await page.goto(self.project_url)
            await page.wait_for_load_state("domcontentloaded")

            for idx, i in enumerate(batch_indices):
                batch = jobs[i : i + self.batch_size]

                if idx == 0:
                    prompt = build_prompt(profile, batch, start_index=i)
                else:
                    prompt = build_continuation_prompt(batch, start_index=i)

                try:
                    response = await self._send_message(page, prompt)
                    parsed = parse_response(response, batch, start_index=i)
                    for job_idx, res in zip(range(i, i + len(batch)), parsed):
                        results[job_idx] = res
                except Exception as e:
                    print(f"  [error] Worker {worker_id} batch failed, skipping {len(batch)} jobs: {e}")
                    for job_idx in range(i, i + len(batch)):
                        results[job_idx] = FailedResult(reason=str(e))
                finally:
                    progress.increment(len(batch))
        finally:
            await page.close()

        return results

    async def _send_message(self, page: Page, prompt: str) -> str:
        editor = page.locator('div[contenteditable="true"][data-testid="chat-input"]').first
        await editor.wait_for(state="visible")
        await page.wait_for_timeout(1000)

        await editor.click()
        await editor.focus()

        inserted = await page.evaluate(
            "(text) => document.execCommand('insertText', false, text)",
            prompt,
        )

        editor_text = await editor.inner_text()

        if not inserted or len(editor_text.strip()) == 0:
            raise ScoringError(
                "Failed to insert prompt into editor",
                raw_response="",
            )

        await page.keyboard.press("Enter")

        streaming = page.locator('[data-is-streaming="true"]')
        await streaming.wait_for(state="attached", timeout=15_000)
        await streaming.wait_for(state="detached", timeout=300_000)

        await page.wait_for_timeout(1000)

        responses = page.locator('.standard-markdown')
        return await responses.last.inner_text()
