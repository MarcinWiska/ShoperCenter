from typing import List, Dict

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, CreateView, DetailView

from .models import Module
from .forms import ModuleCreateForm
from .shoper import fetch_fields, fetch_rows, resolve_path, build_rest_roots


class ModuleListView(LoginRequiredMixin, ListView):
    model = Module
    template_name = 'modules/module_list.html'
    context_object_name = 'modules'

    def get_queryset(self):
        return Module.objects.filter(owner=self.request.user).select_related('shop')


class ModuleCreateView(LoginRequiredMixin, CreateView):
    model = Module
    form_class = ModuleCreateForm
    template_name = 'modules/module_form.html'
    success_url = reverse_lazy('modules:list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Limit shops to current user
        form.fields['shop'].queryset = form.fields['shop'].queryset.filter(owner=self.request.user)
        return form

    def form_valid(self, form):
        form.instance.owner = self.request.user
        resp = super().form_valid(form)
        return redirect('modules:configure', pk=self.object.pk)


@login_required
def configure_fields(request, pk):
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    api_path = resolve_path(module.resource, module.api_path_override)
    fields: List[str] = []
    error: str | None = None
    api_hint_urls = []
    if api_path:
        fields = fetch_fields(module.shop.base_url, module.shop.bearer_token, api_path)
        if not fields:
            p = api_path.strip('/')
            for root in build_rest_roots(module.shop.base_url):
                api_hint_urls.extend([
                    root + p,
                    root + p + '/',
                    root + p + '/?limit=20',
                    root + p + '?limit=20',
                ])
            error = 'Nie udało się pobrać atrybutów z API. Sprawdź URL, token, ustaw własny path albo upewnij się, że moduł ma jakieś dane.'
    else:
        error = 'Nieznana ścieżka API dla wybranego modułu. Uzupełnij własny path.'

    if request.method == 'POST':
        selected = request.POST.getlist('fields')
        config: List[Dict[str, str]] = []
        for idx, key in enumerate(selected):
            label = request.POST.get(f'label__{key}', key)
            config.append({"key": key, "label": label, "order": idx})
        module.fields_config = config
        module.save(update_fields=['fields_config'])
        return redirect('modules:detail', pk=module.pk)

    # Preselect already configured fields
    selected_keys = {f['key'] for f in module.fields_config} if module.fields_config else set()
    return render(request, 'modules/module_configure_fields.html', {
        'module': module,
        'fields': fields,
        'selected_keys': selected_keys,
        'error': error,
        'api_hint_urls': api_hint_urls,
    })


class ModuleDetailView(LoginRequiredMixin, DetailView):
    model = Module
    template_name = 'modules/module_detail.html'
    context_object_name = 'module'

    def get_queryset(self):
        return Module.objects.filter(owner=self.request.user).select_related('shop')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        module: Module = self.object
        api_path = resolve_path(module.resource, module.api_path_override)
        rows = fetch_rows(module.shop.base_url, module.shop.bearer_token, api_path) if api_path else []
        # Build flattened rows based on selected fields
        columns = module.fields_config or []
        ctx['columns'] = columns
        ctx['rows'] = rows
        return ctx

# Create your views here.
