from django.urls import path
from .views import (
    ShopListView,
    ShopCreateView,
    ShopUpdateView,
    ShopDeleteView,
    test_shop_connection,
)

app_name = 'shops'

urlpatterns = [
    path('', ShopListView.as_view(), name='list'),
    path('shops/add/', ShopCreateView.as_view(), name='add'),
    path('shops/<int:pk>/edit/', ShopUpdateView.as_view(), name='edit'),
    path('shops/<int:pk>/delete/', ShopDeleteView.as_view(), name='delete'),
    path('shops/<int:pk>/test/', test_shop_connection, name='test'),
]
