import json
from pathlib import Path
from models import UserProfile

_CONFIG_DIR = Path(__file__).parent / "config"


def load_profile() -> UserProfile:
    return UserProfile(
        background=(_CONFIG_DIR / "background.md").read_text(),
        rules=(_CONFIG_DIR / "rules.md").read_text(),
        fit_criteria=(_CONFIG_DIR / "fit_criteria.md").read_text(),
    )


def load_prefilter() -> dict[str, list[str]]:
    return json.loads((_CONFIG_DIR / "prefilter.json").read_text())


def load_scorer_config(name: str) -> dict:
    return json.loads((_CONFIG_DIR / "scorers" / f"{name}.json").read_text())
