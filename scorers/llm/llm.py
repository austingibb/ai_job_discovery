import os

import requests

from config import load_scorer_config
from models import FailedResult, JobListing, ScoringResult, UserProfile
from scorers.parser import parse_response
from scorers.prompt import build_prompt


class LLMScorer:
    """Generic scorer that works with any OpenAI-compatible or Ollama API."""

    def __init__(self, config_name: str, **overrides: object) -> None:
        config = load_scorer_config(config_name)
        config.update({k: v for k, v in overrides.items() if v is not None})
        self.base_url: str = config["base_url"]
        self.model: str = config["model"]
        self.api: str = config.get("api", "ollama")
        self.batch_size: int = config["batch_size"]
        self.timeout: int = config["timeout"]

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
        results: list[ScoringResult] = []

        for i in range(0, len(jobs), self.batch_size):
            batch = jobs[i : i + self.batch_size]
            pct = round(i / len(jobs) * 100)
            print(f"[{pct:3d}%] Scoring jobs {i + 1}–{min(i + len(batch), len(jobs))} of {len(jobs)}...")

            prompt = build_prompt(profile, batch, start_index=i)

            try:
                response = self._generate(prompt)
                results.extend(parse_response(response, batch, start_index=i))
            except Exception as e:
                print(f"  [error] Batch failed, skipping {len(batch)} jobs: {e}")
                results.extend(FailedResult(reason=str(e)) for _ in batch)

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
