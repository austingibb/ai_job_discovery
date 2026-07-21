import json
from pathlib import Path
from models import UserProfile

_CONFIG_DIR = Path(__file__).parent / "config"
_PROFILES_DIR = _CONFIG_DIR / "profiles"


def _select_profile_dir(profile_name: str) -> Path:
    profile_dir = _PROFILES_DIR / profile_name
    if profile_dir.is_dir():
        print(f"Using profile: {profile_name}")
        return profile_dir
    raise FileNotFoundError(f"Profile '{profile_name}' not found in {_PROFILES_DIR}")


def load_profile(profile_dir: Path) -> UserProfile:
    return UserProfile(
        background=(profile_dir / "background.md").read_text(),
        rules=(profile_dir / "rules.md").read_text(),
        fit_criteria=(profile_dir / "fit_criteria.md").read_text(),
        request_address=bool(load_locations_config(profile_dir)["locations"]),
    )


def load_prefilter(profile_dir: Path) -> dict[str, list[str]]:
    return json.loads((profile_dir / "prefilter.json").read_text())


def load_config() -> dict:
    return json.loads((_CONFIG_DIR / "config.json").read_text())


def load_scraper_config(name: str) -> dict:
    scraper_path = _CONFIG_DIR / "scrapers" / name / "config.json"
    if scraper_path.exists():
        return json.loads(scraper_path.read_text())
    return {}


def load_scorer_config(name: str) -> dict:
    scorer_path = _CONFIG_DIR / "scorers" / name / "config.json"
    if scorer_path.exists():
        return json.loads(scorer_path.read_text())
    return {}


def load_locations_config(profile_dir: Path) -> dict:
    locations_path = profile_dir / "locations.json"
    if not locations_path.exists():
        return {"default_radius_km": 2.5, "locations": []}
    data = json.loads(locations_path.read_text())
    data.setdefault("default_radius_km", 2.5)
    data.setdefault("locations", [])
    return data


def load_dedup_config() -> dict:
    config_path = _CONFIG_DIR / "config.json"
    data = json.loads(config_path.read_text())
    dedup = data.get("dedup", {})
    defaults = {
        "company_threshold": 50,
        "title_threshold": 80,
        "description_threshold": 95,
    }
    defaults.update(dedup)
    return defaults
