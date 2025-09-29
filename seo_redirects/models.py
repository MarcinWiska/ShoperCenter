from django.db import models
from django.contrib.auth import get_user_model

from shops.models import Shop


User = get_user_model()


class RedirectRule(models.Model):
    class RuleType(models.TextChoices):
        URL_TO_URL = 'url_to_url', 'URL → URL'
        PRODUCT_TO_URL = 'product_to_url', 'Product ID → URL'
        CATEGORY_TO_URL = 'category_to_url', 'Category ID → URL'

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
