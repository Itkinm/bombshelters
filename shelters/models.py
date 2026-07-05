from django.db import models


class District(models.Model):
    """Aggregate per-district info (mirrors the old `districts` table)."""

    okrug = models.CharField(max_length=255, blank=True)
    district = models.CharField(max_length=255)
    population = models.CharField(max_length=255, blank=True)
    capacity = models.CharField(max_length=255, blank=True)
    address_raw = models.TextField(blank=True)
    info = models.TextField(blank=True)

    class Meta:
        verbose_name = "district"
        verbose_name_plural = "districts"
        ordering = ("okrug", "district")

    def __str__(self):
        return f"{self.okrug} / {self.district}" if self.okrug else self.district


class Shelter(models.Model):
    """A single bomb shelter address (mirrors the old `addresses` table)."""

    district = models.ForeignKey(
        District,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shelters",
    )
    district_name = models.CharField(max_length=255)
    okrug = models.CharField(max_length=255, blank=True)
    address = models.CharField(max_length=512)
    name = models.CharField(max_length=512, blank=True)
    capacity = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=255, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)

    # Added for admin curation.
    confirmed = models.BooleanField(default=False)
    comment = models.TextField(blank=True)

    class Meta:
        verbose_name = "shelter"
        verbose_name_plural = "shelters"
        ordering = ("okrug", "district_name", "address")

    def __str__(self):
        return self.address
