from django.urls import path
from .views import (
    RedirectRuleListView,
    RedirectRuleCreateView,
    RedirectRuleUpdateView,
    RedirectRuleDeleteView,
    sync_rule,
    pull_redirects,
)

app_name = 'seo_redirects'

urlpatterns = [
    path('', RedirectRuleListView.as_view(), name='list'),
    path('add/', RedirectRuleCreateView.as_view(), name='add'),
    path('<int:pk>/edit/', RedirectRuleUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', RedirectRuleDeleteView.as_view(), name='delete'),
    path('<int:pk>/sync/', sync_rule, name='sync'),
    path('pull/<int:shop_id>/', pull_redirects, name='pull'),
]
