"""Import shelters from the legacy ``shelters.db`` SQLite file into the ORM.

Reads the old ``districts`` and ``addresses`` tables and creates ``District``
and ``Shelter`` rows. New rows default to ``confirmed=False`` / empty comment.
Safe to re-run with ``--flush`` to rebuild from scratch.
"""

import os
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from shelters.models import District, Shelter


class Command(BaseCommand):
    help = "Import shelters/districts from the legacy shelters.db SQLite file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--db",
            default=os.path.join(settings.BASE_DIR, "shelters.db"),
            help="Path to the legacy shelters.db (default: BASE_DIR/shelters.db).",
        )
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing shelters/districts before importing.",
        )

    def handle(self, *args, **options):
        db_path = options["db"]
        if not os.path.exists(db_path):
            raise CommandError(f"Legacy DB not found: {db_path}")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            district_rows = conn.execute(
                "SELECT id, okrug, district, population, capacity, address_raw, info"
                " FROM districts"
            ).fetchall()
            address_rows = conn.execute(
                "SELECT district_id, district, okrug, address, name, capacity, source, lat, lon"
                " FROM addresses"
            ).fetchall()
        finally:
            conn.close()

        with transaction.atomic():
            if options["flush"]:
                Shelter.objects.all().delete()
                District.objects.all().delete()

            old_to_new = {}
            for r in district_rows:
                district = District.objects.create(
                    okrug=r["okrug"] or "",
                    district=r["district"] or "",
                    population=r["population"] or "",
                    capacity=r["capacity"] or "",
                    address_raw=r["address_raw"] or "",
                    info=r["info"] or "",
                )
                old_to_new[r["id"]] = district

            shelters = [
                Shelter(
                    district=old_to_new.get(r["district_id"]),
                    district_name=r["district"] or "",
                    okrug=r["okrug"] or "",
                    address=r["address"] or "",
                    name=r["name"] or "",
                    capacity=r["capacity"] or "",
                    source=r["source"] or "",
                    lat=r["lat"],
                    lon=r["lon"],
                    confirmed=False,
                    comment="",
                )
                for r in address_rows
            ]
            Shelter.objects.bulk_create(shelters, batch_size=1000)

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(district_rows)} districts and {len(address_rows)} shelters."
            )
        )
