from django.contrib import admin
from .models import Module


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("name", "shop", "resource", "owner", "created_at")
    search_fields = ("name", "shop__name", "resource", "owner__username")

# Register your models here.
