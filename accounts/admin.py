from django.contrib import admin

from .models import CoreSettings


@admin.register(CoreSettings)
class CoreSettingsAdmin(admin.ModelAdmin):
    list_display = ("owner", "default_vat_rate", "default_stock_level", "updated_at")
    search_fields = ("owner__username", "owner__email")
