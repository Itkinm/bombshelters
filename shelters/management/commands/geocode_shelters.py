"""Geocode Shelter rows that lack coordinates, directly via the ORM (db.sqlite3).

Unlike the standalone geocode_shelters.py (which works on the legacy
shelters.db), this operates on the live Django DB the bot reads, so results are
usable immediately with no re-import step.

Query building is tolerant of the messy address formats in the data:
  * a region/city prefix is derived from okrug/district_name
    (Moscow's okrug is an АО abbreviation, so it is skipped and "Москва" carries
    the query);
  * the words "дом"/"корпус"/"строение" are stripped/normalized because
    Nominatim returns nothing for e.g. "Москва, Улица Белозерская, дом 23А" but
    resolves "Москва, Улица Белозерская, 23А";
  * progressively looser fallbacks are tried (full address -> street+house ->
    street only) so a row still gets street-level coordinates when the exact
    house is not in OSM.

Nominatim policy: <=1 req/sec + descriptive User-Agent, so requests are
throttled. Safe to re-run: only rows without coordinates are queried.
"""

import re
import time

import requests
from django.core.management.base import BaseCommand

from shelters.models import Shelter

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "bomboubezhishe-shelter-bot/1.0 (Russia shelter finder)"

# For Moscow the okrug column holds an административный округ abbreviation
# (e.g. "СВАО"), which Nominatim can't use; the "Москва" district carries it.
MOSCOW_AO = {
    "ЦАО", "САО", "СВАО", "ВАО", "ЮВАО", "ЮАО", "ЮЗАО", "ЗАО", "СЗАО",
    "ЗелАО", "Новомосковский АО", "Троицкий АО", "НАО", "ТАО",
}

_HOUSE_RE = re.compile(r"\d+[А-Яа-яA-Za-z]?(?:/\d+)?")

# Spelled-out ordinals the source sometimes uses instead of "1-й", "3-й", ...
_ORD_WORDS = {
    "первый": "1-й", "второй": "2-й", "третий": "3-й", "четвертый": "4-й",
    "четвёртый": "4-й", "пятый": "5-й", "шестой": "6-й", "седьмой": "7-й",
    "восьмой": "8-й", "девятый": "9-й", "десятый": "10-й",
    "первая": "1-я", "вторая": "2-я", "третья": "3-я", "четвертая": "4-я",
    "пятая": "5-я",
}
# Street-type words dropped when falling back to a bare proper-name query
# (the source frequently mislabels the type, e.g. проезд written as "Проспект").
_STREET_TYPES = {
    "улица", "ул", "проспект", "пр-т", "просп", "проезд", "переулок", "пер",
    "бульвар", "б-р", "шоссе", "ш", "площадь", "пл", "набережная", "наб",
    "аллея", "тупик", "линия", "квартал",
}

# Bounding box (lon_w, lat_n, lon_e, lat_s) used to keep Moscow lookups from
# matching same-named streets in the surrounding oblast. Covers Moscow within
# and a little beyond the MKAD.
MOSCOW_VIEWBOX = "37.28,55.98,37.97,55.53"


def _place_prefix(okrug, district):
    parts = []
    if okrug and okrug not in MOSCOW_AO:  # region name; skip АО abbrevs
        parts.append(okrug)
    if district and district not in parts:
        parts.append(district)
    return parts


def _normalize_house_parts(rest):
    """Normalize the house/building chunks of an address for Nominatim.

    Only the standalone words дом/корпус/строение are touched; the деревня
    marker "д." is deliberately left alone so village names survive.
    """
    out = []
    for p in rest:
        p = re.sub(r"\bдом\b\s*", "", p, flags=re.I)
        p = re.sub(r"\bкорпус[а]?\b\s*", "к", p, flags=re.I)
        p = re.sub(r"\bстроение\b\s*", "с", p, flags=re.I)
        p = re.sub(r"\bстр\.?\s*", "с", p, flags=re.I)
        p = re.sub(r"\s+", " ", p).strip()
        if p:
            out.append(p)
    return out


def _normalize_street(street):
    """Normalize ordinals in a street name (Первый -> 1-й, 12-ая -> 12-я)."""
    out = []
    for tok in street.split():
        low = tok.lower().strip(".")
        if low in _ORD_WORDS:
            out.append(_ORD_WORDS[low])
            continue
        m = re.match(r"(\d+)-?(ая|яя|ый|ой|ий|я|й)$", low)
        if m:
            suffix = "я" if m.group(2) in ("ая", "яя", "я") else "й"
            out.append(f"{m.group(1)}-{suffix}")
            continue
        out.append(tok)
    return " ".join(out)


def _bare_street(street):
    """Drop street-type words, leaving just the proper name (last-resort query)."""
    toks = [t for t in street.split() if t.lower().strip(".") not in _STREET_TYPES]
    return " ".join(toks)


def build_query_variants(okrug, district, address):
    """Return ordered, deduped Nominatim queries from tightest to loosest."""
    prefix = ", ".join(_place_prefix(okrug, district))
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if not parts:
        return [prefix] if prefix else []

    street = _normalize_street(parts[0])
    bare = _bare_street(street)
    rest = _normalize_house_parts(parts[1:])
    house_num = next((m.group(0) for p in rest for m in [_HOUSE_RE.search(p)] if m), None)

    def with_prefix(tail):
        return f"{prefix}, {tail}" if prefix else tail

    variants = []
    if rest:
        variants.append(with_prefix(f"{street}, {', '.join(rest)}"))
    if house_num:
        variants.append(with_prefix(f"{street}, {house_num}"))
        if bare and bare != street:
            variants.append(with_prefix(f"{bare}, {house_num}"))
    variants.append(with_prefix(street))
    if bare and bare != street:
        variants.append(with_prefix(bare))

    seen, ordered = set(), []
    for q in variants:
        if q and q not in seen:
            seen.add(q)
            ordered.append(q)
    return ordered


def _nominatim(query, viewbox=None):
    params = {"q": query, "format": "json", "countrycodes": "ru", "limit": 1}
    if viewbox:
        params["viewbox"] = viewbox
        params["bounded"] = 1
    resp = requests.get(
        NOMINATIM_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


class Command(BaseCommand):
    help = "Geocode Shelter rows without coordinates via Nominatim (ORM-backed)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", action="append", default=None,
            help="Only geocode rows with this source (repeatable). Default: all.",
        )
        parser.add_argument(
            "--moscow", action="store_true",
            help="Shortcut for --source moscow.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Cap the number of rows processed (for testing).",
        )
        parser.add_argument(
            "--sleep", type=float, default=1.1,
            help="Seconds between requests (Nominatim policy: >=1).",
        )

    def handle(self, *args, **options):
        qs = Shelter.objects.filter(lat__isnull=True) | Shelter.objects.filter(
            lon__isnull=True
        )
        qs = qs.distinct()

        sources = options["source"] or []
        if options["moscow"]:
            sources.append("moscow")
        if sources:
            qs = qs.filter(source__in=sources)

        qs = qs.order_by("id")
        if options["limit"]:
            qs = qs[: options["limit"]]

        rows = list(qs.values_list("id", "okrug", "district_name", "address"))
        if not rows:
            self.stdout.write("No matching rows without coordinates.")
            return

        self.stdout.write(f"Geocoding {len(rows)} row(s) via Nominatim...")
        sleep_s = options["sleep"]
        updated = 0
        for i, (sid, okrug, district, address) in enumerate(rows, 1):
            coords = None
            used = None
            viewbox = MOSCOW_VIEWBOX if district == "Москва" else None
            for query in build_query_variants(okrug, district, address):
                try:
                    coords = _nominatim(query, viewbox=viewbox)
                except Exception as exc:
                    self.stdout.write(f"  [{i}/{len(rows)} id={sid}] ERROR '{query}': {exc}")
                    coords = None
                time.sleep(sleep_s)
                if coords:
                    used = query
                    break

            if coords:
                Shelter.objects.filter(id=sid).update(lat=coords[0], lon=coords[1])
                updated += 1
                self.stdout.write(
                    f"  [{i}/{len(rows)} id={sid}] {used} -> {coords[0]:.6f}, {coords[1]:.6f}"
                )
            else:
                self.stdout.write(f"  [{i}/{len(rows)} id={sid}] {address} -> not found")

        self.stdout.write(self.style.SUCCESS(f"Geocoded {updated}/{len(rows)} row(s)."))
