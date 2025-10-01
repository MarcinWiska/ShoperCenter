from django.urls import path
from .views import (
    ModuleListView,
    ModuleCreateView,
    ModuleDetailView,
    configure_fields,
    configure_fields_json,
    module_data_json,
    product_create_json,
    products_bulk_update_json,
    products_bulk_delete_json,
    product_edit,
    product_edit_json,
    product_redirect_json,
    product_promo_json,
    product_duplicate_json,
    product_delete_json,
)

app_name = 'modules'

urlpatterns = [
    path('', ModuleListView.as_view(), name='list'),
    path('add/', ModuleCreateView.as_view(), name='add'),
    path('<int:pk>/', ModuleDetailView.as_view(), name='detail'),
    path('<int:pk>/configure/', configure_fields, name='configure'),
    path('<int:pk>/configure.json', configure_fields_json, name='configure_json'),
    # Data feed + bulk operations for spreadsheet UI (products only)
    path('<int:pk>/data.json', module_data_json, name='data_json'),
    path('<int:pk>/products/create.json', product_create_json, name='product_create_json'),
    path('<int:pk>/products/bulk_update.json', products_bulk_update_json, name='products_bulk_update_json'),
    path('<int:pk>/products/bulk_delete.json', products_bulk_delete_json, name='products_bulk_delete_json'),
    # Product editing (only for products modules)
    path('<int:pk>/products/<int:item_id>/edit/', product_edit, name='product_edit'),
    path('<int:pk>/products/<int:item_id>/edit.json', product_edit_json, name='product_edit_json'),
    path('<int:pk>/products/<int:item_id>/redirect.json', product_redirect_json, name='product_redirect_json'),
    path('<int:pk>/products/<int:item_id>/promo.json', product_promo_json, name='product_promo_json'),
    path('<int:pk>/products/<int:item_id>/duplicate.json', product_duplicate_json, name='product_duplicate_json'),
    path('<int:pk>/products/<int:item_id>/delete.json', product_delete_json, name='product_delete_json'),
]
