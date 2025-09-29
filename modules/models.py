from django.db import models
from django.contrib.auth import get_user_model
from shops.models import Shop


User = get_user_model()


class Module(models.Model):
    class Resource(models.TextChoices):
        PRODUCTS = 'products', 'Products'
        ORDERS = 'orders', 'Orders'
        CATEGORIES = 'categories', 'Categories'
        USERS = 'users', 'Users'
        PRODUCERS = 'producers', 'Producers'
        SHIPPINGS = 'shippings', 'Shippings'
        PAYMENTS = 'payments', 'Payments'
        SUBSCRIBERS = 'subscribers', 'Subscribers'
        TAXES = 'taxes', 'Taxes'
        UNITS = 'units', 'Units'

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='modules')
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='modules')
    name = models.CharField(max_length=120)
    resource = models.CharField(max_length=64, choices=Resource.choices)
    api_path_override = models.CharField(
        max_length=128, blank=True, help_text='Opcjonalny własny path API (np. products)'
    )
    fields_config = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.resource})"

# Create your models here.
