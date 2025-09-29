from django.contrib import admin
from .models import Shop


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "base_url", "created_at")
    search_fields = ("name", "base_url", "owner__username")

# Register your models here.
