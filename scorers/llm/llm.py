import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from config import load_scorer_config
from scorers.parser import parse_response
from scorers.prompt import build_prompt
from models import AIScorer, FailedResult, JobListing, ScoringResult, UserProfile


class LLMScorer(AIScorer):
    """Generic scorer that works with any OpenAI-compatible or Ollama API."""

    def __init__(self, config_name: str, **overrides: object) -> None:
        config = load_scorer_config(config_name)
        config.update({k: v for k, v in overrides.items() if v is not None})
        self.base_url: str = config["base_url"]
        self.model: str = config["model"]
        self.api: str = config.get("api", "ollama")
        self.batch_size: int = config["batch_size"]
        self.timeout: int = config["timeout"]
        self.max_concurrent: int = config.get("max_concurrent", 1)

        # Optional API key via env var
        api_key_env = config.get("api_key_env")
        self.api_key: str = ""
        if api_key_env:
            self.api_key = os.environ.get(api_key_env, "")
            if not self.api_key:
                raise ValueError(
                    f"API key required. Set the {api_key_env} environment variable."
                )

        # Optional extra headers and body fields for provider-specific features
        self.extra_headers: dict[str, str] = config.get("extra_headers", {})
        self.extra_body: dict = config.get("extra_body", {})

    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        batches = [
            (i, jobs[i : i + self.batch_size])
            for i in range(0, len(jobs), self.batch_size)
        ]
        completed_batches = 0
        results_by_index: dict[int, list[ScoringResult]] = {}

        def _score_batch(start_index: int, batch: list[JobListing]) -> tuple[int, list[ScoringResult]]:
            prompt = build_prompt(profile, batch, start_index=start_index)
            try:
                response = self._generate(prompt)
                return start_index, parse_response(response, batch, start_index=start_index)
            except Exception as e:
                print(f"  [error] Batch failed, skipping {len(batch)} jobs: {e}")
                return start_index, [FailedResult(reason=str(e)) for _ in batch]

        max_concurrent = min(self.max_concurrent, len(batches))
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {
                executor.submit(_score_batch, i, batch): i
                for i, batch in batches
            }

            for future in as_completed(futures):
                start_index, batch_results = future.result()
                results_by_index[start_index] = batch_results
                completed_batches += 1
                pct = round(completed_batches / len(batches) * 100)
                print(f"[{pct:3d}%] Completed batch at index {start_index} ({completed_batches}/{len(batches)} batches)")

        results: list[ScoringResult] = []
        for i, _ in batches:
            results.extend(results_by_index[i])

        print("[100%] Scoring complete.")
        return results

    def _generate(self, prompt: str) -> str:
        if self.api == "openai":
            return self._generate_openai(prompt)
        return self._generate_ollama(prompt)

    def _generate_ollama(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["response"]

    def _generate_openai(self, prompt: str) -> str:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)

        body: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            **self.extra_body,
        }

        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
