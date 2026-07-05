from django.db import models


class CivilDefenseBody(models.Model):
    """A civil-defense (ГО и ЧС) body, unifying the city/region/district CSVs."""

    LEVEL_CITY = "city"
    LEVEL_REGION = "region"
    LEVEL_DISTRICT = "district"
    LEVEL_CHOICES = [
        (LEVEL_CITY, "city"),
        (LEVEL_REGION, "region"),
        (LEVEL_DISTRICT, "district"),
    ]

    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, db_index=True)

    # Matching keys (used depending on level).
    city = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=255, blank=True)
    federal_district = models.CharField(max_length=255, blank=True)
    area = models.CharField(max_length=255, blank=True)
    district = models.CharField(max_length=255, blank=True)

    # Body details.
    body_name = models.TextField(blank=True)
    org_name = models.TextField(blank=True)
    body_type = models.CharField(max_length=64, blank=True)
    address = models.TextField(blank=True)
    phone = models.TextField(blank=True)
    email = models.CharField(max_length=255, blank=True)
    website = models.CharField(max_length=512, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    source_url = models.CharField(max_length=512, blank=True)
    notes = models.TextField(blank=True)

    # Added for admin curation.
    custom_instructions = models.TextField(blank=True)

    class Meta:
        verbose_name = "civil defense body"
        verbose_name_plural = "civil defense bodies"
        ordering = ("level", "region", "city", "district")

    def __str__(self):
        label = self.city or self.region or self.district or self.body_name
        return f"[{self.level}] {label}"
