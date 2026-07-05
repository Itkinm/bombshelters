"""Import civil-defense bodies from the legacy CSV files into the ORM.

Loads three CSVs into the unified ``CivilDefenseBody`` model, tagging each row
with its ``level`` (city / region / district). New rows get empty
``custom_instructions``. Safe to re-run with ``--flush``.
"""

import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from civildefense.models import CivilDefenseBody


def _to_float(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Import civil-defense bodies from the legacy CSV files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing civil-defense bodies before importing.",
        )

    def _read(self, name):
        path = os.path.join(settings.BASE_DIR, name)
        if not os.path.exists(path):
            self.stdout.write(self.style.WARNING(f"Skipping missing file: {name}"))
            return []
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def handle(self, *args, **options):
        objs = []

        for row in self._read("cities_civil_defense.csv"):
            objs.append(
                CivilDefenseBody(
                    level=CivilDefenseBody.LEVEL_CITY,
                    city=(row.get("city") or "").strip(),
                    region=(row.get("region") or "").strip(),
                    body_name=(row.get("body_name") or "").strip(),
                    body_type=(row.get("body_type") or "").strip(),
                    address=(row.get("address") or "").strip(),
                    phone=(row.get("phone") or "").strip(),
                    email=(row.get("email") or "").strip(),
                    website=(row.get("website") or "").strip(),
                    source_url=(row.get("source_url") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )

        for row in self._read("regions_civil_defense.csv"):
            objs.append(
                CivilDefenseBody(
                    level=CivilDefenseBody.LEVEL_REGION,
                    region=(row.get("region") or "").strip(),
                    federal_district=(row.get("federal_district") or "").strip(),
                    body_name=(row.get("body_name") or "").strip(),
                    body_type=(row.get("body_type") or "").strip(),
                    address=(row.get("address") or "").strip(),
                    phone=(row.get("phone") or "").strip(),
                    email=(row.get("email") or "").strip(),
                    website=(row.get("website") or "").strip(),
                    source_url=(row.get("source_url") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )

        # moscow_spb_districts already covers both Moscow and SPB districts,
        # matching what the bot's DISTRICTS_CSV used previously.
        for row in self._read("moscow_spb_districts_civil_defense.csv"):
            objs.append(
                CivilDefenseBody(
                    level=CivilDefenseBody.LEVEL_DISTRICT,
                    city=(row.get("city") or "").strip(),
                    area=(row.get("area") or "").strip(),
                    district=(row.get("district") or "").strip(),
                    body_name=(row.get("body_name") or "").strip(),
                    org_name=(row.get("org_name") or "").strip(),
                    body_type=(row.get("body_type") or "").strip(),
                    address=(row.get("address") or "").strip(),
                    phone=(row.get("phone") or "").strip(),
                    email=(row.get("email") or "").strip(),
                    website=(row.get("website") or "").strip(),
                    lat=_to_float(row.get("lat")),
                    lon=_to_float(row.get("lon")),
                    source_url=(row.get("source_url") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )

        with transaction.atomic():
            if options["flush"]:
                CivilDefenseBody.objects.all().delete()
            CivilDefenseBody.objects.bulk_create(objs, batch_size=1000)

        self.stdout.write(
            self.style.SUCCESS(f"Imported {len(objs)} civil-defense bodies.")
        )
