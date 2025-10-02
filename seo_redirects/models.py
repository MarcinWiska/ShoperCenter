from django.db import models
from django.contrib.auth import get_user_model

from shops.models import Shop


User = get_user_model()


class CategoryHierarchy(models.Model):
    """
    Przechowuje hierarchię kategorii dla każdego sklepu.
    Automatycznie budowana na podstawie struktury kategorii w Shoper.
    """
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='category_hierarchies')
    category_id = models.IntegerField(help_text="ID kategorii w Shoper")
    category_name = models.CharField(max_length=255, help_text="Nazwa kategorii")
    category_slug = models.SlugField(max_length=255, help_text="Slug kategorii dla URL")
    
    # Hierarchia jako JSON - lista slugów od głównej do tej kategorii
    # Przykład: ["dla-niej", "sukienki", "sukienki-letnie"]
    path_slugs = models.JSONField(default=list, help_text="Pełna ścieżka slugów")
    
    # Poziom w hierarchii (0 = główna kategoria)
    level = models.IntegerField(default=0, help_text="Poziom zagnieżdżenia (0 = root)")
    
    # Metadane
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'seo_category_hierarchy'
        unique_together = [('shop', 'category_id')]
        indexes = [
            models.Index(fields=['shop', 'category_id']),
            models.Index(fields=['shop', 'level']),
        ]
        verbose_name = 'Hierarchia Kategorii'
        verbose_name_plural = 'Hierarchie Kategorii'
    
    def __str__(self):
        path = ' → '.join(self.path_slugs) if self.path_slugs else self.category_slug
        return f"{self.shop.name}: {path}"
    
    @property
    def full_path(self):
        """Zwraca pełną ścieżkę jako string dla URL"""
        return '/'.join(self.path_slugs) if self.path_slugs else self.category_slug


class RedirectRule(models.Model):
    class RuleType(models.TextChoices):
        URL_TO_URL = 'url_to_url', 'URL → URL'
        PRODUCT_TO_URL = 'product_to_url', 'Product ID → URL'
        CATEGORY_TO_URL = 'category_to_url', 'Category ID → URL'

    class TargetType(models.IntegerChoices):
        OWN = 0, 'Własny URL'
        PRODUCT = 1, 'Produkt'
        CATEGORY = 2, 'Kategoria produktu'
        PRODUCER = 3, 'Producent'
        INFO_PAGE = 4, 'Strona informacyjna'
        NEWS = 5, 'Aktualność'
        NEWS_CATEGORY = 6, 'Kategoria aktualności'

    STATUS_CHOICES = (
        (301, '301 Moved Permanently'),
        (302, '302 Found / Temporary'),
    )

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='seo_redirect_rules')
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='seo_redirect_rules')
    rule_type = models.CharField(max_length=32, choices=RuleType.choices, default=RuleType.URL_TO_URL)

    # Fields for URL→URL
    source_url = models.CharField(max_length=512, blank=True, help_text='Źródłowy URL (np. /stara-strona)')

    # Fields for product/category variants
    product_id = models.BigIntegerField(null=True, blank=True)
    category_id = models.BigIntegerField(null=True, blank=True)

    # Common target
    target_url = models.CharField(max_length=512, help_text='Docelowy URL (np. /nowa-strona)')
    target_type = models.IntegerField(choices=TargetType.choices, default=TargetType.OWN)
    target_object_id = models.BigIntegerField(null=True, blank=True)

    status_code = models.IntegerField(choices=STATUS_CHOICES, default=301)
    active = models.BooleanField(default=True)

    # Remote tracking (Shoper)
    remote_id = models.CharField(max_length=64, blank=True)
    last_sync_status = models.CharField(max_length=200, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.shop.name}: {self.rule_type} -> {self.target_url}"

    @property
    def source_full_url(self) -> str:
        if not self.source_url:
            return ''
        return self.shop.build_storefront_url(self.source_url)

    @property
    def target_full_url(self) -> str:
        if not self.target_url:
            return ''
        return self.shop.build_storefront_url(self.target_url)
