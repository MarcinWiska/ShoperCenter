from django.db import models
from django.contrib.auth import get_user_model


User = get_user_model()


class Shop(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shops')
    name = models.CharField(max_length=100, help_text='Twoja własna nazwa sklepu')
    base_url = models.URLField(help_text='Adres API sklepu (np. https://twojsklep.pl/webapi)')
    bearer_token = models.CharField(max_length=255, help_text='Bearer Token do API Shopera')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

# Create your models here.
