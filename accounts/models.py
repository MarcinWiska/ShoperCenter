from django.conf import settings
from django.db import models


class CoreSettings(models.Model):
    """Global application-level settings per owner."""

    VAT_RATE_CHOICES = [
        ("23", "23%"),
        ("8", "8%"),
        ("5", "5%"),
        ("0", "0%"),
        ("ZW", "ZW (zwolnione)"),
        ("NP", "NP (nie podlega)"),
    ]

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="core_settings",
    )
    default_vat_rate = models.CharField(
        max_length=8,
        choices=VAT_RATE_CHOICES,
        default="23",
        help_text="Domyślna stawka VAT stosowana przy tworzeniu nowych produktów.",
    )
    default_stock_level = models.PositiveIntegerField(
        default=0,
        help_text="Domyślny stan magazynowy przypisywany nowym produktom (szt.).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ustawienia główne"
        verbose_name_plural = "Ustawienia główne"

    def __str__(self) -> str:
        return f"Core settings for {self.owner}" if self.owner_id else "Core settings"
