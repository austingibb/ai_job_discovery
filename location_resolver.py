import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

from models import ScoredResult

_CACHE_PATH = Path("output/geocode_cache.json")
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim rejects requests without a User-Agent identifying the application.
_USER_AGENT = "ai_job_discovery"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Spherical (haversine) model; ~0.5% error vs the ellipsoid, fine for
    # ranking jobs by rough proximity.
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def load_cache(path: Path = _CACHE_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_cache(cache: dict, path: Path = _CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2))


def geocode(address: str, cache: dict) -> tuple[float, float] | None:
    """Geocode an address via Nominatim, returning (lat, lon) or None.

    Results (including failures, stored as null) are cached by address string
    so repeated runs don't re-query. Sleeps 1s after each network call per
    Nominatim's rate limit policy; cache hits don't sleep.
    """
    if address in cache:
        cached = cache[address]
        return tuple(cached) if cached else None

    url = f"{_NOMINATIM_URL}?{urllib.parse.urlencode({'q': address, 'format': 'json', 'limit': 1})}"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            results = json.loads(resp.read())
    except Exception as e:
        # Transient network errors are not cached, so the address is retried next run.
        print(f"  [warn] Geocoding failed for '{address}': {e}")
        time.sleep(1)
        return None

    time.sleep(1)
    if results:
        coords = (float(results[0]["lat"]), float(results[0]["lon"]))
        cache[address] = list(coords)
        return coords
    cache[address] = None
    return None


def resolve(
    results: list[ScoredResult],
    location_config: dict,
    cache: dict | None = None,
    cache_path: Path = _CACHE_PATH,
) -> None:
    """Assign location_tier and location_note to each scored result.

    Tier 1: within the radius of at least one configured location.
    Tier 2: address geocoded but outside all configured radii.
    Tier 3: no address, or geocoding failed.

    Pass a prefilled `cache` dict to bypass real geocoding (e.g. in tests);
    otherwise the cache is loaded from and saved to `cache_path`.
    """
    locations = location_config.get("locations", [])
    if not locations:
        return

    default_radius = location_config.get("default_radius_km", 2.5)
    persist = cache is None
    if cache is None:
        cache = load_cache(cache_path)

    try:
        for result in results:
            if not result.address:
                result.location_tier = 3
                result.location_note = "no address"
                continue

            coords = geocode(result.address, cache)
            if coords is None:
                result.location_tier = 3
                result.location_note = "no address"
                continue

            lat, lon = coords
            nearest_name = ""
            nearest_km = math.inf
            matched_name = ""
            matched_km = math.inf
            for loc in locations:
                distance = haversine_km(lat, lon, loc["lat"], loc["lon"])
                if distance < nearest_km:
                    nearest_km = distance
                    nearest_name = loc["name"]
                if distance <= loc.get("radius_km", default_radius) and distance < matched_km:
                    matched_km = distance
                    matched_name = loc["name"]

            if matched_name:
                result.location_tier = 1
                result.location_note = f"{matched_km:.1f} km from {matched_name}"
            else:
                result.location_tier = 2
                result.location_note = f"{nearest_km:.1f} km from {nearest_name} (outside radius)"
    finally:
        if persist:
            save_cache(cache, cache_path)
