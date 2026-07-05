from django.contrib import admin

from .models import CivilDefenseBody


@admin.register(CivilDefenseBody)
class CivilDefenseBodyAdmin(admin.ModelAdmin):
    list_display = ("__str__", "level", "body_type", "has_instructions")
    list_filter = ("level", "body_type")
    search_fields = ("city", "region", "district", "area", "body_name", "org_name")
    list_per_page = 50
    fields = (
        "custom_instructions",
        "level",
        "city",
        "region",
        "federal_district",
        "area",
        "district",
        "body_name",
        "org_name",
        "body_type",
        "address",
        "phone",
        "email",
        "website",
        "lat",
        "lon",
        "source_url",
        "notes",
    )

    @admin.display(boolean=True, description="instructions")
    def has_instructions(self, obj):
        return bool(obj.custom_instructions.strip())
