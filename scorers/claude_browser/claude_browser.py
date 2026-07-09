import asyncio

from playwright.async_api import Page, async_playwright

from config import load_config, load_scorer_config
from models import AIScorer, FailedResult, JobListing, ScoringResult, ScoringError, UserProfile
from scorers.parser import parse_response
from scorers.prompt import build_prompt, build_continuation_prompt
from scorers.claude_browser.dom_capture import wait_or_capture

class Progress:
    def __init__(self, total: int):
        self.total = total
        self.completed = 0

    def increment(self, count: int):
        self.completed += count

class ClaudeBrowserScorer(AIScorer):
    def __init__(self, project_url: str | None = None) -> None:
        global_config = load_config()
        scorer_config = load_scorer_config("claude_browser")
        self.cdp_url: str = global_config["cdp_url"]
        self.project_url: str = project_url or scorer_config.get("default_url", "https://claude.ai/new")
        self.batch_size: int = scorer_config.get("batch_size", 2)
        self.concurrency: int = scorer_config.get("concurrency", 1)
        self.cleanup_chat: bool = scorer_config.get("cleanup_chat", False)
        self.model: str | None = scorer_config.get("model", None)
        # Attach the (pruned) full page HTML to failure evidence. High-recall but
        # the biggest token cost for the fixer -- flip to false to fall back to
        # the near-free overlay/candidate evidence if OpenRouter spend spikes.
        self.attach_page_html: bool = scorer_config.get("attach_page_html", True)
        # Set when chat cleanup fails after a scoring run (message + dom_context
        # evidence). Deliberately does NOT fail scoring -- results are already
        # in hand -- but the canary reads it so leaked chats surface as
        # SCORER_DRIFT instead of accumulating silently in claude.ai history.
        self.last_cleanup_error: dict | None = None

    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        self.last_cleanup_error = None
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
        chat_created = False

        try:
            await page.goto(self.project_url)
            await page.wait_for_load_state("domcontentloaded")

            if self.model:
                await self._select_model(page)

            for idx, i in enumerate(batch_indices):
                batch = jobs[i : i + self.batch_size]

                if idx == 0:
                    prompt = build_prompt(profile, batch, start_index=i)
                else:
                    prompt = build_continuation_prompt(batch, start_index=i)

                try:
                    response = await self._send_message(page, prompt)
                    chat_created = True
                    parsed = parse_response(response, batch, start_index=i)
                    for job_idx, res in zip(range(i, i + len(batch)), parsed):
                        results[job_idx] = res
                except Exception as e:
                    print(f"  [error] Worker {worker_id} batch failed, skipping {len(batch)} jobs: {e}")
                    for job_idx in range(i, i + len(batch)):
                        results[job_idx] = FailedResult(reason=str(e))
                finally:
                    progress.increment(len(batch))
            
            if self.cleanup_chat and chat_created:
                await self._delete_current_chat(page)
        finally:
            await page.close()

        return results

    async def _select_model(self, page: Page) -> None:
        """Select the configured model via the model selector dropdown.

        Every brittle step goes through wait_or_capture: on drift it captures
        failure-time DOM evidence (open overlays + nearest candidates + pruned
        page HTML) so triage gets an apt, groundable fix instead of a blind guess.
        """
        dropdown = await wait_or_capture(
            page, 'button[data-testid="model-selector-dropdown"]',
            what="model selector dropdown button", timeout=10_000,
            attach_page_html=self.attach_page_html,
        )

        # Check if the desired model is already selected
        current_label = await dropdown.get_attribute("aria-label") or ""
        if self.model and self.model in current_label:
            print(f"  Model already set to {self.model}, skipping selection.")
            return

        # Open the dropdown
        await dropdown.click()
        await page.wait_for_timeout(500)

        # Find and click the matching model option
        await wait_or_capture(
            page, '[role="menu"]', what="model menu popup", timeout=5_000,
            attach_page_html=self.attach_page_html,
        )
        model_selector = f'[role="menuitemradio"]:has(.font-ui:text-is("{self.model}"))'
        model_option = await wait_or_capture(
            page, model_selector, what=f"model option {self.model!r}", timeout=5_000,
            attach_page_html=self.attach_page_html,
        )
        await model_option.click()
        await page.wait_for_timeout(500)

        print(f"  Selected model: {self.model}")

    async def _send_message(self, page: Page, prompt: str) -> str:
        editor = await wait_or_capture(
            page, 'div[contenteditable="true"][data-testid="chat-input"]',
            what="chat input field", timeout=30_000,
            attach_page_html=self.attach_page_html,
        )
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

    async def _delete_current_chat(self, page: Page):
        """Delete the chat this worker created. A failure never raises (scoring
        results are already in hand) but is recorded on self.last_cleanup_error
        with DOM evidence so the canary can flag leaked chats as drift instead
        of letting them accumulate silently in claude.ai history."""
        chat_url = page.url
        try:
            # 1. Hover the active chat item to reveal the "More options" button
            active_chat = await wait_or_capture(
                page, 'a[aria-current="page"]',
                what="active chat item in sidebar", timeout=10_000,
                attach_page_html=self.attach_page_html,
            )
            await active_chat.hover()
            await page.wait_for_timeout(500)

            # 2. Click the "More options" button for the active chat
            more_options_btn = await wait_or_capture(
                page, 'li:has(a[aria-current="page"]) button[aria-label*="More options"]',
                what="chat 'More options' button", timeout=10_000,
                attach_page_html=self.attach_page_html,
            )
            await more_options_btn.click()

            # 3. Click the "Delete" option in the menu
            delete_option = await wait_or_capture(
                page, '[data-testid="delete-chat-trigger"]',
                what="Delete option in chat menu", timeout=10_000,
                attach_page_html=self.attach_page_html,
            )
            await delete_option.click()

            # 4. Click the "Delete" confirmation button in the dialog
            confirm_btn = await wait_or_capture(
                page, '[role="alertdialog"] button:has-text("Delete")',
                what="Delete confirmation button", timeout=10_000,
                attach_page_html=self.attach_page_html,
            )
            await confirm_btn.click()

            # 5. Verify it actually deleted: claude.ai navigates away from the
            # chat URL. Clicking a button is not proof the chat is gone.
            try:
                await page.wait_for_url(lambda url: url != chat_url, timeout=10_000)
            except Exception:
                raise ScoringError(
                    f"clicked Delete but still on {page.url}; chat may not be deleted",
                    raw_response="",
                )

            print("Successfully deleted the chat.")
        except Exception as e:
            print(f"Failed to delete the chat: {e}")
            self.last_cleanup_error = {
                "chat_url": chat_url,
                "error": repr(e)[:300],
                "dom_context": getattr(e, "dom_context", None),
            }
