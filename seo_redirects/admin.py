from django.contrib import admin
from .models import RedirectRule


@admin.register(RedirectRule)
class RedirectRuleAdmin(admin.ModelAdmin):
    list_display = ("shop", "rule_type", "source_url", "product_id", "category_id", "target_url", "status_code", "remote_id")
    search_fields = ("source_url", "target_url", "shop__name")
