"""Structured result types for the live canary.

This is the contract the downstream triage harness (Phase 4) consumes. It is
deliberately self-contained and JSON-serializable so the harness can read it
without importing pipeline internals.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Classification(str, Enum):
    """Why the pipeline is (or is not) healthy, ordered by detection layer.

    The value is what a downstream router keys on. ACTIONS below documents the
    intended human/automation response, but the harness owns the actual routing.
    """

    HEALTHY = "HEALTHY"
    # Layer 1: cannot reach the Chrome debug instance over CDP.
    ENVIRONMENT_CDP_DOWN = "ENVIRONMENT_CDP_DOWN"
    # Layer 2: preset URL landed on a login wall / unauthenticated redirect.
    ENVIRONMENT_AUTH = "ENVIRONMENT_AUTH"
    # Layer 3: page loaded but the expected results container is missing.
    URL_OR_STRUCTURE_DRIFT = "URL_OR_STRUCTURE_DRIFT"
    # Layer 4: container healthy but listings do not parse into JobListings.
    SCRAPER_SELECTOR_DRIFT = "SCRAPER_SELECTOR_DRIFT"
    # Layer 5: listings parse but the scorer output does not parse via parser.py.
    SCORER_DRIFT = "SCORER_DRIFT"
    # Cross-preset: a single preset's URL/params drifted while others are healthy.
    CANARY_MAINTENANCE = "CANARY_MAINTENANCE"


# Intended response per classification. The harness reads these as hints; it is
# the source of truth for routing in Phase 4, not this table.
ACTIONS: dict[Classification, str] = {
    Classification.HEALTHY: "none",
    Classification.ENVIRONMENT_CDP_DOWN: "tell_user_start_chrome",  # never a code fix
    Classification.ENVIRONMENT_AUTH: "tell_user_relogin",  # never a code fix
    Classification.URL_OR_STRUCTURE_DRIFT: "propose_fix",  # mechanical first
    Classification.SCRAPER_SELECTOR_DRIFT: "propose_fix",
    Classification.SCORER_DRIFT: "propose_fix",
    Classification.CANARY_MAINTENANCE: "low_priority_alert",  # never a code fix
}


class Layer(str, Enum):
    """The precondition layers, checked in order. The first to fail classifies."""

    CDP = "CDP"  # 1
    AUTH = "AUTH"  # 2
    RESULTS_CONTAINER = "RESULTS_CONTAINER"  # 3
    LISTINGS_PARSE = "LISTINGS_PARSE"  # 4
    SCORER_PARSE = "SCORER_PARSE"  # 5


# Maps the first failing layer to its classification.
LAYER_CLASSIFICATION: dict[Layer, Classification] = {
    Layer.CDP: Classification.ENVIRONMENT_CDP_DOWN,
    Layer.AUTH: Classification.ENVIRONMENT_AUTH,
    Layer.RESULTS_CONTAINER: Classification.URL_OR_STRUCTURE_DRIFT,
    Layer.LISTINGS_PARSE: Classification.SCRAPER_SELECTOR_DRIFT,
    Layer.SCORER_PARSE: Classification.SCORER_DRIFT,
}


@dataclass
class PresetResult:
    """Outcome of running the layered chain against a single preset URL."""

    name: str
    url: str
    healthy: bool
    job_count: int = 0
    # The first layer that failed, or None when healthy.
    failed_layer: Layer | None = None
    classification: Classification = Classification.HEALTHY
    # Evidence captured for the escalation packet. Keys vary by failed layer,
    # e.g. dom_snippet, attempted_url, redirect_target, expected_shape,
    # actual_shape, raw_scorer_response, exception.
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["failed_layer"] = self.failed_layer.value if self.failed_layer else None
        d["classification"] = self.classification.value
        return d


@dataclass
class CanaryResult:
    """Aggregate canary outcome and the foundation of the Phase 4 escalation packet."""

    classification: Classification
    healthy: bool
    escalate: bool
    summary: str
    presets: list[PresetResult] = field(default_factory=list)
    last_known_good_commit: str | None = None
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def failed_presets(self) -> list[str]:
        return [p.name for p in self.presets if not p.healthy]

    def to_dict(self) -> dict:
        return {
            "classification": self.classification.value,
            "healthy": self.healthy,
            "escalate": self.escalate,
            "summary": self.summary,
            "action": ACTIONS[self.classification],
            "failed_presets": self.failed_presets,
            "presets": [p.to_dict() for p in self.presets],
            "last_known_good_commit": self.last_known_good_commit,
            "checked_at": self.checked_at,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
