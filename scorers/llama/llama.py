import json
from pathlib import Path

import requests

from models import FailedResult, JobListing, ScoringResult, UserProfile
from scorers.parser import parse_response
from scorers.prompt import build_prompt

_CONFIG_PATH = Path(__file__).parent / "config.json"


class LlamaScorer:
    def __init__(self, **overrides: object) -> None:
        config = json.loads(_CONFIG_PATH.read_text())
        config.update({k: v for k, v in overrides.items() if v is not None})
        self.base_url: str = config["base_url"]
        self.model: str = config["model"]
        self.api: str = config.get("api", "ollama")
        self.batch_size: int = config["batch_size"]
        self.timeout: int = config["timeout"]

    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]:
        results: list[ScoringResult] = []

        for i in range(0, len(jobs), self.batch_size):
            batch = jobs[i : i + self.batch_size]
            pct = round(i / len(jobs) * 100)
            print(f"[{pct:3d}%] Scoring jobs {i + 1}–{min(i + len(batch), len(jobs))} of {len(jobs)}...")

            # Always send the full prompt — no chat continuation with a small context window.
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
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
