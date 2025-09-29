import requests
from urllib.parse import urljoin
from modules.shoper import build_rest_roots

from django.contrib import messages
from django.shortcuts import redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import Shop
from .forms import ShopForm


class ShopListView(LoginRequiredMixin, ListView):
    model = Shop
    template_name = 'shops/shop_list.html'
    context_object_name = 'shops'

    def get_queryset(self):
        return Shop.objects.filter(owner=self.request.user)


class ShopCreateView(LoginRequiredMixin, CreateView):
    model = Shop
    form_class = ShopForm
    template_name = 'shops/shop_form.html'
    success_url = reverse_lazy('shops:list')

    def form_valid(self, form):
        form.instance.owner = self.request.user
        # TODO: Optionally validate token against Shoper API
        return super().form_valid(form)


class ShopUpdateView(LoginRequiredMixin, UpdateView):
    model = Shop
    form_class = ShopForm
    template_name = 'shops/shop_form.html'
    success_url = reverse_lazy('shops:list')

    def get_queryset(self):
        return Shop.objects.filter(owner=self.request.user)


class ShopDeleteView(LoginRequiredMixin, DeleteView):
    model = Shop
    template_name = 'shops/shop_confirm_delete.html'
    success_url = reverse_lazy('shops:list')

    def get_queryset(self):
        return Shop.objects.filter(owner=self.request.user)


@login_required
def test_shop_connection(request, pk):
    shop = Shop.objects.filter(owner=request.user, pk=pk).first()
    if not shop:
        messages.error(request, 'Sklep nie istnieje lub nie masz dostępu.')
        return redirect('shops:list')

    # Wyznacz poprawny REST root i sprawdź application/version
    test_url = None
    for rest_root in build_rest_roots(shop.base_url):
        candidate = urljoin(rest_root, 'application/version')
        try:
            resp = requests.get(
                candidate,
                headers={'Authorization': f'Bearer {shop.bearer_token}', 'Accept': 'application/json'},
                timeout=8,
            )
            if resp.status_code == 200:
                test_url = candidate
                break
        except requests.RequestException:
            continue
    if test_url:
        messages.success(request, 'Połączenie OK ✔️ (application/version)')
        return redirect('shops:list')
    # Jeśli żaden nie zadziałał, spróbuj ostatni i przekaż kod
    rest_root = build_rest_roots(shop.base_url)[0]
    test_url = urljoin(rest_root, 'application/version')
    try:
        resp = requests.get(test_url, headers={'Authorization': f'Bearer {shop.bearer_token}', 'Accept': 'application/json'}, timeout=8)
        if resp.status_code == 200:
            messages.success(request, 'Połączenie OK ✔️ (application/version)')
        else:
            messages.error(request, f'Błąd połączenia ({resp.status_code}) — sprawdź URL/token')
    except requests.RequestException:
        messages.error(request, 'Nie udało się połączyć z API — sprawdź URL/token')
    return redirect('shops:list')

# Create your views here.
