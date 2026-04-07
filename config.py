import json
from pathlib import Path
from models import UserProfile

_CONFIG_DIR = Path(__file__).parent / "config"
_PROFILES_DIR = _CONFIG_DIR / "profiles"


def _select_profile_dir() -> Path:
    """Interactively select a profile, or fall back to config/ if no profiles exist."""
    if not _PROFILES_DIR.exists():
        return _CONFIG_DIR

    profiles = sorted(p.name for p in _PROFILES_DIR.iterdir() if p.is_dir())
    if not profiles:
        return _CONFIG_DIR

    if len(profiles) == 1:
        print(f"Using profile: {profiles[0]}")
        return _PROFILES_DIR / profiles[0]

    print("\nAvailable profiles:")
    for i, name in enumerate(profiles, start=1):
        print(f"  {i}. {name}")

    while True:
        choice = input(f"\nSelect a profile (1-{len(profiles)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(profiles):
            selected = profiles[int(choice) - 1]
            print(f"Using profile: {selected}")
            return _PROFILES_DIR / selected
        print(f"Invalid choice. Enter a number between 1 and {len(profiles)}.")


def load_profile(profile_dir: Path) -> UserProfile:
    return UserProfile(
        background=(profile_dir / "background.md").read_text(),
        rules=(profile_dir / "rules.md").read_text(),
        fit_criteria=(profile_dir / "fit_criteria.md").read_text(),
    )


def load_prefilter(profile_dir: Path) -> dict[str, list[str]]:
    return json.loads((profile_dir / "prefilter.json").read_text())


def load_config() -> dict:
    return json.loads((_CONFIG_DIR / "config.json").read_text())


def load_scorer_config(name: str) -> dict:
    scorer_path = _CONFIG_DIR / "scorers" / f"{name}.json"
    if scorer_path.exists():
        return json.loads(scorer_path.read_text())
    return {}
