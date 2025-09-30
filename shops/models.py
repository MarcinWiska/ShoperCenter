from urllib.parse import urljoin

from django.db import models
from django.contrib.auth import get_user_model


User = get_user_model()


class Shop(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shops')
    name = models.CharField(max_length=100, help_text='Twoja własna nazwa sklepu')
    base_url = models.URLField(help_text='Adres API sklepu (np. https://twojsklep.pl/webapi)')
    bearer_token = models.CharField(max_length=512, help_text='Bearer Token do API Shopera (access token 64 znaki)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def storefront_base(self) -> str:
        url = self.base_url.rstrip('/')
        lowered = url.lower()
        for suffix in ('/webapi/rest', '/webapi', '/rest'):
            if lowered.endswith(suffix):
                url = url[:-len(suffix)]
                break
        return url.rstrip('/')

    def build_storefront_url(self, path: str) -> str:
        base = self.storefront_base() or self.base_url.rstrip('/')
        if not path:
            return base
        return urljoin(base + '/', path.lstrip('/'))

# Create your models here.
