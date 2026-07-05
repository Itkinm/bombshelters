from django.contrib import admin

from .models import District, Shelter


@admin.register(Shelter)
class ShelterAdmin(admin.ModelAdmin):
    list_display = (
        "address",
        "okrug",
        "district_name",
        "confirmed",
        "has_coords",
        "source",
    )
    list_filter = ("confirmed", "okrug", "source")
    list_editable = ("confirmed",)
    search_fields = ("address", "district_name", "name", "comment")
    list_per_page = 50
    fields = (
        "confirmed",
        "comment",
        "address",
        "name",
        "okrug",
        "district_name",
        "district",
        "capacity",
        "source",
        "lat",
        "lon",
    )
    autocomplete_fields = ("district",)

    @admin.display(boolean=True, description="coords")
    def has_coords(self, obj):
        return obj.lat is not None and obj.lon is not None


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("district", "okrug", "population", "capacity")
    list_filter = ("okrug",)
    search_fields = ("district", "okrug")
