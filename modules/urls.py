from django.urls import path
from .views import ModuleListView, ModuleCreateView, ModuleDetailView, configure_fields

app_name = 'modules'

urlpatterns = [
    path('', ModuleListView.as_view(), name='list'),
    path('add/', ModuleCreateView.as_view(), name='add'),
    path('<int:pk>/', ModuleDetailView.as_view(), name='detail'),
    path('<int:pk>/configure/', configure_fields, name='configure'),
]

