from django.urls import path
from .views import (
    RedirectRuleListView,
    RedirectRuleCreateView,
    RedirectRuleUpdateView,
    RedirectRuleDeleteView,
    sync_rule,
    pull_redirects,
    generate_seo_redirects,
    preview_seo_url,
    propose_seo_redirects,
    refresh_hierarchy,
)

app_name = 'seo_redirects'

urlpatterns = [
    path('', RedirectRuleListView.as_view(), name='list'),
    path('add/', RedirectRuleCreateView.as_view(), name='add'),
    path('<int:pk>/edit/', RedirectRuleUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', RedirectRuleDeleteView.as_view(), name='delete'),
    path('<int:pk>/sync/', sync_rule, name='sync'),
    path('pull/<int:shop_id>/', pull_redirects, name='pull'),
    path('generate/<int:shop_id>/', generate_seo_redirects, name='generate_seo_redirects'),
    path('preview/<int:shop_id>/', preview_seo_url, name='preview_seo_url'),
    path('propose/<int:shop_id>/', propose_seo_redirects, name='propose_seo_redirects'),
    path('refresh-hierarchy/<int:shop_id>/', refresh_hierarchy, name='refresh_hierarchy'),
]
