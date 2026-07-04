"""Look up the civil-defense (ГО и ЧС) government body responsible for a location.

Two reference tables live next to this module:
  - cities_civil_defense.csv   (keyed by `city`, 50 largest cities)
  - regions_civil_defense.csv  (keyed by `region`, all federal subjects)

Rule: if the user's city is in the cities table, return that body; otherwise
fall back to the body for the user's region.
"""

import csv
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CITIES_CSV = os.path.join(BASE_DIR, "cities_civil_defense.csv")
REGIONS_CSV = os.path.join(BASE_DIR, "regions_civil_defense.csv")


def _norm(s):
    """Normalize a place name for tolerant matching."""
    if not s:
        return ""
    s = s.strip().lower().replace("ё", "е")
    # Drop common administrative prefixes.
    for prefix in ("город ", "г. ", "г."):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.strip()


def _load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


_CITIES = _load(CITIES_CSV)
_REGIONS = _load(REGIONS_CSV)


def find_city(city):
    if not city:
        return None
    target = _norm(city)
    for row in _CITIES:
        if _norm(row.get("city")) == target:
            return row
    return None


def find_region(region):
    if not region:
        return None
    target = _norm(region)
    # Exact (normalized) match first.
    for row in _REGIONS:
        if _norm(row.get("region")) == target:
            return row
    # Fall back to a containment match (handles e.g.
    # "Кемеровская область — Кузбасс" vs "Кемеровская область").
    for row in _REGIONS:
        rn = _norm(row.get("region"))
        if rn and (rn in target or target in rn):
            return row
    return None


def lookup_civil_defense(city=None, region=None):
    """Return {'row': <dict>, 'level': 'city'|'region'} or None.

    City takes precedence over region, per the routing rule.
    """
    row = find_city(city)
    if row:
        return {"row": row, "level": "city"}
    row = find_region(region)
    if row:
        return {"row": row, "level": "region"}
    return None


def format_body(result):
    """Format a lookup result as a Russian-language message block."""
    if not result:
        return None
    row = result["row"]
    scope = "город" if result["level"] == "city" else "регион"
    lines = [f"Ответственный орган ГО и ЧС ({scope}):", row.get("body_name", "").strip()]

    address = (row.get("address") or "").strip()
    phone = (row.get("phone") or "").strip()
    email = (row.get("email") or "").strip()
    website = (row.get("website") or "").strip()

    if address:
        lines.append(f"Адрес: {address}")
    if phone:
        lines.append(f"Телефон: {phone}")
    if email:
        lines.append(f"Email: {email}")
    if website:
        lines.append(f"Сайт: {website}")
    return "\n".join(line for line in lines if line)
