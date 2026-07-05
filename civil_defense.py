"""Look up the civil-defense (ГО и ЧС) government body responsible for a location.

Two reference tables live next to this module:
  - cities_civil_defense.csv   (keyed by `city`, 50 largest cities)
  - regions_civil_defense.csv  (keyed by `region`, all federal subjects)

Rule: if the user's city is in the cities table, return that body; otherwise
fall back to the body for the user's region.
"""

import re

# Fields pulled from the ORM for each civil-defense body (keys mirror the old
# CSV column names so the matching/formatting helpers work unchanged).
_BODY_FIELDS = (
    "city", "region", "federal_district", "area", "district",
    "body_name", "org_name", "body_type", "address", "phone", "email",
    "website", "source_url", "notes", "custom_instructions",
)

# Cities that have district-level bodies in the districts table.
DISTRICT_CITIES = {"москва", "санкт-петербург"}

# Whole-word tokens dropped when normalizing a district name for matching.
_DISTRICT_DROP = {
    "район", "поселение", "посёлок", "поселок", "деревня", "село", "город",
    "округ", "муниципальный", "административный", "городской", "квартал",
}


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


def _norm_district(s):
    """Normalize a district (район) name into a token set for matching."""
    if not s:
        return set()
    s = s.lower().replace("ё", "е")
    tokens = re.findall(r"[а-я0-9-]+", s)
    return {t for t in tokens if t and t not in _DISTRICT_DROP}


def _bodies(level):
    """Fetch civil-defense bodies of a given level from the ORM as dicts.

    Queried per lookup (not cached) so admin edits take effect without a
    bot restart. Row keys match the old CSV columns.
    """
    from civildefense.models import CivilDefenseBody

    return list(CivilDefenseBody.objects.filter(level=level).values(*_BODY_FIELDS))


def find_city(city):
    if not city:
        return None
    target = _norm(city)
    for row in _bodies("city"):
        if _norm(row.get("city")) == target:
            return row
    return None


def find_region(region):
    if not region:
        return None
    target = _norm(region)
    rows = _bodies("region")
    # Exact (normalized) match first.
    for row in rows:
        if _norm(row.get("region")) == target:
            return row
    # Fall back to a containment match (handles e.g.
    # "Кемеровская область — Кузбасс" vs "Кемеровская область").
    for row in rows:
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


def is_district_city(city):
    """True if the city has district-level bodies (Moscow / SPB)."""
    return _norm(city) in DISTRICT_CITIES


def find_district_body(city, district_candidates):
    """Find the district-level (район) body for a Moscow/SPB user.

    city: the user's city (e.g. "Москва"/"Санкт-Петербург").
    district_candidates: iterable of possible район names from geocoding.
    Returns a row dict or None.
    """
    if not city:
        return None
    city_n = _norm(city)
    if city_n not in DISTRICT_CITIES:
        return None

    rows = [r for r in _bodies("district") if _norm(r.get("city")) == city_n]
    if not rows:
        return None

    cand_sets = [_norm_district(c) for c in (district_candidates or [])]
    cand_sets = [c for c in cand_sets if c]
    if not cand_sets:
        return None

    for row in rows:
        rset = _norm_district(row.get("district"))
        if not rset:
            continue
        for cand in cand_sets:
            # All row tokens present in a candidate (exact or more specific).
            if rset == cand or rset <= cand:
                return row
    return None


def format_body_text(city, region, district_candidates=None):
    """Formatted civil-defense contact block for a location.

    District-level body for Moscow/SPB, otherwise the region/city body.
    Returns a string or None.
    """
    if is_district_city(city):
        row = find_district_body(city, district_candidates)
        return format_district_body(row) if row else None
    result = lookup_civil_defense(city, region)
    return format_body(result) if result else None


def location_instructions(city, region, district_candidates=None):
    """Admin-authored custom instructions for the responsible body, or None."""
    if is_district_city(city):
        row = find_district_body(city, district_candidates)
    else:
        result = lookup_civil_defense(city, region)
        row = result["row"] if result else None
    if not row:
        return None
    return (row.get("custom_instructions") or "").strip() or None


def _format_contacts(lines, row):
    for label, key in (("Адрес", "address"), ("Телефон", "phone"),
                       ("Email", "email"), ("Сайт", "website")):
        val = (row.get(key) or "").strip()
        if val:
            lines.append(f"{label}: {val}")


def _append_instructions(lines, row):
    """Append admin-authored custom instructions, if any, to a message block."""
    instructions = (row.get("custom_instructions") or "").strip()
    if instructions:
        lines.append("")
        lines.append(instructions)


def format_body(result):
    """Format a city/region lookup result as a Russian-language message block."""
    if not result:
        return None
    row = result["row"]
    scope = "город" if result["level"] == "city" else "регион"
    lines = [f"Ответственный орган ГО и ЧС ({scope}):", row.get("body_name", "").strip()]
    _format_contacts(lines, row)
    _append_instructions(lines, row)
    return "\n".join(line for line in lines if line)


def format_district_body(row):
    """Format a district-level (район) body as a Russian-language message block."""
    if not row:
        return None
    district = (row.get("district") or "").strip()
    if (row.get("body_type") or "").strip() == "ukp":
        header = "Районный учебно-консультационный пункт ГО и ЧС"
    else:
        header = "Районный орган ГО и ЧС"
    if district:
        header += f" ({district})"
    header += ":"

    name = (row.get("org_name") or "").strip() or (row.get("body_name") or "").strip()
    lines = [header]
    if name:
        lines.append(name)
    _format_contacts(lines, row)
    _append_instructions(lines, row)
    return "\n".join(line for line in lines if line)
