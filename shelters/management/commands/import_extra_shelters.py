"""Import extra shelters into the Django DB from a prepared CSV.

The CSV is produced by ``manage.py build_extra_shelters_csv`` (run locally, where
the Moscow xlsx and minzdrav.gov.ru are reachable) and then copied to the server.
This command itself needs neither network nor the xlsx — it only reads the CSV,
so it is safe to run on the remote.

Expected columns (header row required):
    source, okrug, district_name, address, name, capacity, confirmed, lat, lon, comment

Idempotent: every ``source`` present in the CSV has its existing rows deleted
before the CSV rows are inserted, so re-running replaces cleanly.
"""

import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from shelters.models import District, Shelter

REQUIRED_FIELDS = {"source", "district_name", "address"}


def _to_float(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _to_bool(v):
    return str(v).strip().lower() in {"1", "true", "yes", "да"}


class Command(BaseCommand):
    help = "Import extra shelters from a prepared CSV (see build_extra_shelters_csv)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default=os.path.join(settings.BASE_DIR, "extra_shelters.csv"),
            help="Path to the CSV (default: BASE_DIR/extra_shelters.csv).",
        )

    def handle(self, *args, **options):
        path = options["csv"]
        if not os.path.exists(path):
            raise CommandError(f"CSV not found: {path}")

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or not REQUIRED_FIELDS.issubset(reader.fieldnames):
                raise CommandError(
                    f"CSV must have at least columns {sorted(REQUIRED_FIELDS)}; "
                    f"got {reader.fieldnames}"
                )
            rows = list(reader)

        if not rows:
            self.stdout.write("CSV has no data rows; nothing to import.")
            return

        district_cache = {}

        def get_district(okrug, district):
            key = (okrug, district)
            if key not in district_cache:
                district_cache[key], _ = District.objects.get_or_create(
                    okrug=okrug or "", district=district or "",
                )
            return district_cache[key]

        objs = []
        sources = set()
        skipped = 0
        for r in rows:
            source = (r.get("source") or "").strip()
            address = (r.get("address") or "").strip()
            district_name = (r.get("district_name") or "").strip()
            if not source or not address:
                skipped += 1
                continue
            sources.add(source)
            okrug = (r.get("okrug") or "").strip()
            objs.append(Shelter(
                district=get_district(okrug, district_name),
                district_name=district_name,
                okrug=okrug,
                address=address[:512],
                name=(r.get("name") or "").strip()[:512],
                capacity=(r.get("capacity") or "").strip()[:255],
                source=source[:255],
                lat=_to_float(r.get("lat")),
                lon=_to_float(r.get("lon")),
                confirmed=_to_bool(r.get("confirmed")),
                comment=(r.get("comment") or "").strip(),
            ))

        with transaction.atomic():
            deleted = Shelter.objects.filter(source__in=sources).delete()[0]
            Shelter.objects.bulk_create(objs, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f"Imported {len(objs)} shelter(s) from {os.path.basename(path)} "
            f"across sources {sorted(sources)} "
            f"(replaced {deleted} existing; skipped {skipped} bad row(s))."
        ))
