from django.urls import path
from .views import dashboard_view, core_settings_view

app_name = 'dashboard'

urlpatterns = [
    path('', dashboard_view, name='home'),
    path('core-settings/', core_settings_view, name='core_settings'),
]
