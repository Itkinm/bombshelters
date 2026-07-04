"""Find the closest bomb shelter to a user-submitted address.

Geocoding: OpenStreetMap Nominatim (no API key).
Routing: OpenRouteService matrix API (free key via env var ORS_API_KEY),
supporting both foot-walking and driving-car. Falls back to straight-line
(haversine) distance when no key is configured or ORS is unavailable.
"""

import math
import os
import sqlite3

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "shelters.db")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "bomboubezhishe-shelter-bot/1.0 (Moscow shelter finder)"

ORS_API_KEY = os.environ.get("ORS_API_KEY")
ORS_MATRIX_URL = "https://api.heigit.org/openrouteservice/v2/matrix/{profile}"
VALID_PROFILES = {"foot-walking", "driving-car"}

# Average walking / driving speeds (m/s) used to estimate duration in the
# haversine fallback when ORS is unavailable.
FALLBACK_SPEED_MS = {"foot-walking": 1.4, "driving-car": 8.3}


def geocode(query):
    """Geocode an address string via Nominatim. Returns (lat, lon) or None."""
    if not query or not query.strip():
        return None
    resp = requests.get(
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "json",
            "countrycodes": "ru",
            "limit": 1,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def _extract_city_region(address):
    """Pull (city, region) from a Nominatim address-details dict."""
    if not address:
        return None, None
    city = (
        address.get("city")
        or address.get("town")
        or address.get("municipality")
        or address.get("village")
        or address.get("hamlet")
    )
    region = address.get("state") or address.get("region")
    return city, region


def geocode_details(query):
    """Geocode an address and also return its city/region.

    Returns (lat, lon, city, region) or None. One Nominatim call.
    """
    if not query or not query.strip():
        return None
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "json",
                "countrycodes": "ru",
                "limit": 1,
                "addressdetails": 1,
                "accept-language": "ru",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    if not data:
        return None
    item = data[0]
    city, region = _extract_city_region(item.get("address"))
    return float(item["lat"]), float(item["lon"]), city, region


def reverse_geocode(lat, lon):
    """Reverse-geocode coordinates to (city, region). Returns (None, None) on failure."""
    try:
        resp = requests.get(
            NOMINATIM_REVERSE_URL,
            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
                "addressdetails": 1,
                "accept-language": "ru",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None, None
    return _extract_city_region(data.get("address"))


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points in meters."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _haversine_matrix(origin, destinations, profile):
    """Fallback: straight-line distances/durations from origin to each dest."""
    speed = FALLBACK_SPEED_MS.get(profile, FALLBACK_SPEED_MS["foot-walking"])
    distances, durations = [], []
    for lat, lon in destinations:
        d = haversine(origin[0], origin[1], lat, lon)
        distances.append(d)
        durations.append(d / speed)
    return distances, durations


def route_distances(origin, destinations, profile="foot-walking"):
    """Route distances (m) and durations (s) from one origin to many destinations.

    origin: (lat, lon). destinations: list of (lat, lon).
    Returns (distances, durations, source) where source is "ors" or "haversine".
    Uses a single ORS matrix call; falls back to haversine on any failure.
    """
    if profile not in VALID_PROFILES:
        raise ValueError(f"profile must be one of {sorted(VALID_PROFILES)}")
    if not destinations:
        return [], [], "ors" if ORS_API_KEY else "haversine"

    if not ORS_API_KEY:
        d, t = _haversine_matrix(origin, destinations, profile)
        return d, t, "haversine"

    # ORS expects [lon, lat]; source index 0, destinations 1..N.
    locations = [[origin[1], origin[0]]] + [[lon, lat] for lat, lon in destinations]
    dest_indices = list(range(1, len(locations)))
    try:
        resp = requests.post(
            ORS_MATRIX_URL.format(profile=profile),
            json={
                "locations": locations,
                "sources": [0],
                "destinations": dest_indices,
                "metrics": ["distance", "duration"],
                "units": "m",
            },
            headers={
                "Authorization": ORS_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        distances = data["distances"][0]
        durations = data["durations"][0]
        # ORS returns null for unreachable points; treat those as infinite.
        distances = [d if d is not None else math.inf for d in distances]
        durations = [t if t is not None else math.inf for t in durations]
        return distances, durations, "ors"
    except Exception:
        d, t = _haversine_matrix(origin, destinations, profile)
        return d, t, "haversine"


def _load_shelters():
    """Load shelters that have cached coordinates."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT district, okrug, address, lat, lon FROM addresses"
            " WHERE lat IS NOT NULL AND lon IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def find_closest_shelter_by_coords(lat, lon, profile="foot-walking"):
    """Find the closest shelter to a (lat, lon) origin by route distance.

    Returns a dict with district, okrug, address, lat, lon, distance_m,
    duration_s, source, and yandex_maps_url, or None if there are no shelters
    with coordinates.
    """
    shelters = _load_shelters()
    if not shelters:
        return None

    origin = (lat, lon)
    destinations = [(s["lat"], s["lon"]) for s in shelters]
    distances, durations, source = route_distances(origin, destinations, profile)

    best_i = min(range(len(shelters)), key=lambda i: distances[i])
    best = shelters[best_i]
    return {
        "district": best["district"],
        "okrug": best["okrug"],
        "address": best["address"],
        "lat": best["lat"],
        "lon": best["lon"],
        "distance_m": distances[best_i],
        "duration_s": durations[best_i],
        "source": source,
        "yandex_maps_url": (
            f"https://yandex.ru/maps/?pt={best['lon']},{best['lat']}&z=17&l=map"
        ),
    }


def find_closest_shelter(user_address, profile="foot-walking"):
    """Find the closest shelter to a user-submitted address by route distance.

    Geocodes the address, then delegates to find_closest_shelter_by_coords.
    Returns None if the address can't be geocoded or there are no shelters.
    """
    origin = geocode(user_address)
    if origin is None:
        return None
    return find_closest_shelter_by_coords(origin[0], origin[1], profile)


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) or "Москва, Тверская улица, 1"
    result = find_closest_shelter(query)
    if result is None:
        print(f"No shelter found for: {query!r}")
    else:
        print(f"Closest shelter to {query!r}:")
        print(f"  {result['okrug']} / {result['district']}: {result['address']}")
        print(
            f"  {result['distance_m'] / 1000:.2f} km,"
            f" ~{result['duration_s'] / 60:.0f} min ({result['source']})"
        )
        print(f"  {result['yandex_maps_url']}")
