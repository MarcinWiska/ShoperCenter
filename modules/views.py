from typing import List, Dict, Any, Tuple
from copy import deepcopy
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse, HttpRequest
import json
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, CreateView, DetailView
from django.views.decorators.http import require_http_methods

from .models import Module
from .forms import ModuleCreateForm
from .shoper import (
    fetch_fields,
    fetch_rows,
    resolve_path,
    build_rest_roots,
    fetch_item,
    dot_get,
    unflatten,
    update_product,
    create_product,
    delete_product,
    is_editable_product_field,
    get_recommended_product_fields,
    resolve_tax_id,
)
from accounts.models import CoreSettings
from seo_redirects.models import RedirectRule
from seo_redirects.services import sync_redirect_rule
from seo_redirects.helpers import guess_product_path

logger = logging.getLogger(__name__)


@method_decorator(ensure_csrf_cookie, name='dispatch')
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
    
    # Dla produktów - dodaj zalecane pola
    recommended_fields = {}
    if module.resource == Module.Resource.PRODUCTS:
        recommended_list = get_recommended_product_fields()
        recommended_fields = {f["key"]: f for f in recommended_list}
    
    if api_path:
        fields = fetch_fields(module.shop.base_url, module.shop.bearer_token, api_path)
        
        # Jeśli to produkty i nie ma wystarczająco dużo pól z API, dodaj zalecane
        if module.resource == Module.Resource.PRODUCTS and len(fields) < 10:
            # Dodaj zalecane pola które nie są jeszcze na liście
            for rec_field in recommended_fields.keys():
                if rec_field not in fields:
                    fields.append(rec_field)
            logger.info(f"Added recommended fields for products, total fields: {len(fields)}")
        
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
        # Jeśli nie ma ścieżki API, ale to produkty - użyj zalecanych pól
        if module.resource == Module.Resource.PRODUCTS:
            fields = list(recommended_fields.keys())
            logger.info(f"Using recommended fields for products: {len(fields)} fields")
        else:
            error = 'Nieznana ścieżka API dla wybranego modułu. Uzupełnij własny path.'

    if request.method == 'POST':
        selected = request.POST.getlist('fields')
        config: List[Dict[str, str]] = []
        for idx, key in enumerate(selected):
            # Użyj zalecanej etykiety jeśli dostępna
            default_label = recommended_fields.get(key, {}).get('label', key)
            label = request.POST.get(f'label__{key}', default_label)
            config.append({"key": key, "label": label, "order": idx})
        module.fields_config = config
        module.save(update_fields=['fields_config'])
        return redirect('modules:detail', pk=module.pk)

    # Preselect already configured fields
    selected_keys = {f['key'] for f in module.fields_config} if module.fields_config else set()
    
    # Jeśli nie ma jeszcze konfiguracji dla produktów, zaznacz najważniejsze pola
    if module.resource == Module.Resource.PRODUCTS and not selected_keys and recommended_fields:
        important_fields = [
            'product_id', 'translations.pl_PL.name', 'code', 'ean', 
            'stock.price', 'stock.stock', 'translations.pl_PL.active',
            'category_id', 'producer_id'
        ]
        selected_keys = {key for key in important_fields if key in fields}
        logger.info(f"Pre-selected important product fields: {selected_keys}")
    
    # Informacyjnie zaznacz pola nieedytowalne dla produktów
    non_editable_keys = set()
    if module.resource == Module.Resource.PRODUCTS:
        non_editable_keys = {k for k in fields if not is_editable_product_field(k)}
    
    # recommended_fields is already a flat mapping {key: info}
    flat_recommended_fields = recommended_fields if module.resource == Module.Resource.PRODUCTS else {}
    
    return render(request, 'modules/module_configure_fields.html', {
        'module': module,
        'fields': fields,
        'selected_keys': selected_keys,
        'error': error,
        'api_hint_urls': api_hint_urls,
        'non_editable_keys': non_editable_keys,
        'recommended_fields': flat_recommended_fields,
    })


@login_required
def configure_fields_json(request: HttpRequest, pk: int):
    """JSON API for configuring module fields from the modules list modal.
    - GET: returns available fields, selected keys, recommended map, non-editable keys
    - POST: accepts {fields: [keys], labels?: {key: label}} and saves configuration
    """
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    api_path = resolve_path(module.resource, module.api_path_override)
    fields: List[str] = []
    error: str | None = None

    # Recommended map for products
    recommended_map: Dict[str, Dict[str, Any]] = {}
    if module.resource == Module.Resource.PRODUCTS:
        recommended_list = get_recommended_product_fields()
        recommended_map = {f["key"]: f for f in recommended_list}

    if request.method == 'GET':
        if api_path:
            fields = fetch_fields(module.shop.base_url, module.shop.bearer_token, api_path)
            if module.resource == Module.Resource.PRODUCTS and len(fields) < 10:
                for rec_key in recommended_map.keys():
                    if rec_key not in fields:
                        fields.append(rec_key)
        else:
            # No path; for products provide recommended keys as fallback
            if module.resource == Module.Resource.PRODUCTS:
                fields = list(recommended_map.keys())
            else:
                fields = []

        selected_keys = [f['key'] for f in module.fields_config] if module.fields_config else []
        non_editable_keys = []
        if module.resource == Module.Resource.PRODUCTS:
            non_editable_keys = [k for k in fields if not is_editable_product_field(k)]

        return JsonResponse({
            'ok': True,
            'module': {'id': module.pk, 'name': module.name, 'resource': module.resource},
            'fields': fields,
            'selected_keys': selected_keys,
            'recommended_fields': recommended_map,
            'non_editable_keys': non_editable_keys,
            'error': error,
        })

    # POST: save selection
    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    new_fields = data.get('fields') or []
    labels_map = data.get('labels') or {}
    if not isinstance(new_fields, list):
        return JsonResponse({'ok': False, 'error': 'Invalid fields list'}, status=400)

    # Build config preserving order
    config: List[Dict[str, Any]] = []
    for idx, key in enumerate(new_fields):
        if not isinstance(key, str):
            continue
        default_label = labels_map.get(key) or recommended_map.get(key, {}).get('label') or key
        config.append({'key': key, 'label': default_label, 'order': idx})

    module.fields_config = config
    module.save(update_fields=['fields_config'])
    return JsonResponse({'ok': True})


@method_decorator(ensure_csrf_cookie, name='dispatch')
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
        # Fetch all rows (limit=0 means no limit)
        rows = fetch_rows(module.shop.base_url, module.shop.bearer_token, api_path, limit=0) if api_path else []
        # Try to detect ID per row for products so we can link to edit
        rows_with_id: List[Dict[str, Any]] = []
        id_keys = [
            'product_id',
            'id',
            'product.id',
            'product.product_id',
            'productId',
            'productID',
            'id_product',
        ]
        for row in rows:
            row_copy = dict(row)
            found_id = None
            for k in id_keys:
                found_id = dot_get(row, k)
                if found_id is not None and str(found_id).strip() != '':
                    break
            if found_id is not None:
                # Use a safe key for template access (no leading underscore)
                row_copy['item_id'] = found_id
            rows_with_id.append(row_copy)
        # Build flattened rows based on selected fields
        columns = module.fields_config or []
        ctx['columns'] = columns
        ctx['rows'] = rows_with_id
        core_settings = None
        try:
            core_settings = CoreSettings.objects.select_related(None).filter(owner=self.request.user).first()
        except Exception:
            core_settings = None
        ctx['core_settings'] = core_settings
        ctx['core_settings_data'] = {
            'vat_rate': getattr(core_settings, 'default_vat_rate', None),
            'stock_level': getattr(core_settings, 'default_stock_level', None),
        }
        return ctx


@login_required
@require_http_methods(["POST"])
def product_create_json(request: HttpRequest, pk: int):
    """Create a new product via Shoper API.
    Expects JSON payload {payload: {...}} with required product fields.
    Returns {ok, product_id?, message?, row?}.
    """
    logger.info("product_create_json called for module %s", pk)

    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        return JsonResponse({'ok': False, 'error': 'Dostępne tylko dla modułu produktów.'}, status=400)

    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        logger.warning("Invalid JSON payload in product_create_json for module %s", pk)
        return JsonResponse({'ok': False, 'error': 'Nieprawidłowy JSON.'}, status=400)

    payload_input = data.get('payload')
    if not isinstance(payload_input, dict):
        return JsonResponse({'ok': False, 'error': 'Brak danych produktu w żądaniu.'}, status=400)

    payload: Dict[str, Any] = deepcopy(payload_input)

    errors: List[str] = []

    # Validate category_id
    category_id = payload.get('category_id')
    try:
        category_id_int = int(category_id)
        if category_id_int <= 0:
            raise ValueError
        payload['category_id'] = category_id_int
    except (TypeError, ValueError):
        errors.append('Podaj poprawne ID kategorii (> 0).')

    # Validate string fields
    code = str(payload.get('code') or '').strip()
    if not code:
        errors.append('Kod produktu jest wymagany.')
    else:
        payload['code'] = code

    pkwiu = str(payload.get('pkwiu') or '').strip()
    if not pkwiu:
        errors.append('PKWiU jest wymagane.')
    else:
        payload['pkwiu'] = pkwiu

    # Stock validation
    stock = payload.get('stock')
    if not isinstance(stock, dict):
        stock = {}
    price_raw = stock.get('price')
    if isinstance(price_raw, str):
        price_raw = price_raw.replace(',', '.').strip()
    try:
        price_value = float(price_raw)
    except (TypeError, ValueError):
        price_value = None
    if price_value is None:
        errors.append('Cena bazowa jest wymagana i musi być liczbą.')
    elif price_value <= 0:
        errors.append('Cena bazowa musi być większa od 0.')
    else:
        stock['price'] = price_value
    stock['active'] = bool(stock.get('active', True))
    stock['default'] = bool(stock.get('default', True))
    payload['stock'] = stock

    # Translations validation (pl_PL mandatory)
    translations = payload.get('translations')
    if not isinstance(translations, dict):
        translations = {}
    pl_trans = translations.get('pl_PL')
    if not isinstance(pl_trans, dict):
        pl_trans = {}
    name = str(pl_trans.get('name') or '').strip()
    if not name:
        errors.append('Nazwa (pl_PL) jest wymagana.')
    else:
        pl_trans['name'] = name

    active_val = pl_trans.get('active')
    if isinstance(active_val, bool):
        active = active_val
    elif isinstance(active_val, str):
        active = active_val.strip().lower() in {'1', 'true', 'tak', 'yes', 'y'}
    elif isinstance(active_val, (int, float)):
        active = active_val != 0
    else:
        # Default to True if missing
        active = True
    pl_trans['active'] = active

    translations['pl_PL'] = pl_trans
    payload['translations'] = translations

    # Fill defaults from core settings when values are missing
    core_settings = CoreSettings.objects.filter(owner=request.user).first()
    if core_settings:
        vat_default = getattr(core_settings, 'default_vat_rate', None)
        if vat_default and (payload.get('tax_id') is None or str(payload.get('tax_id')).strip() == ''):
            resolved_tax_id = resolve_tax_id(module.shop.base_url, module.shop.bearer_token, vat_default)
            if resolved_tax_id is not None:
                payload['tax_id'] = resolved_tax_id
            else:
                logger.warning(
                    "Nie udało się zmapować domyślnej stawki VAT '%s' na tax_id dla modułu %s",
                    vat_default,
                    pk,
                )

        stock_value = stock.get('stock') if isinstance(stock, dict) else None
        if (stock_value is None or stock_value == '') and core_settings.default_stock_level is not None:
            stock['stock'] = core_settings.default_stock_level
            payload['stock'] = stock

    if errors:
        logger.info("Validation errors while creating product in module %s: %s", pk, errors)
        return JsonResponse({'ok': False, 'error': ' '.join(errors)}, status=400)

    logger.info("Sending product create request for module %s with keys: %s", pk, list(payload.keys()))
    ok, msg, new_id = create_product(module.shop.base_url, module.shop.bearer_token, payload)
    if not ok:
        logger.error("Failed to create product for module %s: %s", pk, msg)
        return JsonResponse({'ok': False, 'error': msg}, status=502)

    response: Dict[str, Any] = {'ok': True, 'message': msg, 'product_id': new_id}

    # Optionally fetch the newly created product to provide grid row snapshot
    api_path = resolve_path(module.resource, module.api_path_override) or 'products'
    if new_id is not None and api_path:
        try:
            new_item = fetch_item(module.shop.base_url, module.shop.bearer_token, api_path, new_id)
            if new_item:
                row_map: Dict[str, Any] = {'item_id': new_id}
                for col in module.fields_config or []:
                    key = col.get('key')
                    if not key:
                        continue
                    val = dot_get(new_item, key)
                    if isinstance(val, list):
                        row_map[key] = val
                    elif isinstance(val, dict):
                        try:
                            row_map[key] = json.dumps(val, ensure_ascii=False)
                        except Exception:
                            row_map[key] = str(val)
                    else:
                        row_map[key] = val
                response['row'] = row_map
        except Exception as exc:
            logger.warning("Failed to fetch newly created product %s: %s", new_id, exc)

    return JsonResponse(response)


@login_required
def product_edit(request, pk: int, item_id: int):
    """Edit a single product from a module using partial update.
    Only changed fields are sent to Shoper.
    """
    logger.info(f"User {request.user.id} editing product {item_id} from module {pk}")
    
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        messages.error(request, 'Edycja jest dostępna tylko dla modułu produktów.')
        return redirect('modules:detail', pk=module.pk)

    api_path = resolve_path(module.resource, module.api_path_override) or 'products'
    product = fetch_item(module.shop.base_url, module.shop.bearer_token, api_path, item_id)
    if not product:
        logger.error(f"Failed to fetch product {item_id} from {api_path}")
        messages.error(request, 'Nie udało się pobrać produktu z API.')
        return redirect('modules:detail', pk=module.pk)

    # Decide which fields are editable: use configured columns
    columns = module.fields_config or []

    def field_meta(key: str, label: str) -> Tuple[str, str, Any, bool]:
        val = dot_get(product, key)
        # Determine simple type for the editor
        if isinstance(val, bool):
            type_name = 'bool'
        elif isinstance(val, (int, float)):
            type_name = 'number'
        else:
            type_name = 'text'
        editable_flag = is_editable_product_field(key)
        return key, type_name, val, editable_flag

    editable = [
        {
            'key': f['key'],
            'label': f.get('label') or f['key'],
            'type': field_meta(f['key'], f.get('label') or f['key'])[1],
            'value': field_meta(f['key'], f.get('label') or f['key'])[2],
            'editable': field_meta(f['key'], f.get('label') or f['key'])[3],
        }
        for f in columns
    ]

    # Add field categories for enhanced UI
    recommended_list = get_recommended_product_fields()
    rec_by_key = {f['key']: f for f in recommended_list}
    field_categories: Dict[str, List[Dict[str, Any]]] = {}

    # Organize editable fields by category (fallback to 'Inne')
    for field in editable:
        field_key = field['key']
        category = rec_by_key.get(field_key, {}).get('category', 'Inne')
        field_categories.setdefault(category, []).append(field)

    if request.method == 'POST':
        logger.info(f"Processing POST request for product {item_id}")
        changed_flat: Dict[str, Any] = {}
        for f in editable:
            if not f.get('editable', True):
                logger.debug(f"Skipping non-editable field: {f['key']}")
                continue  # skip non-editable fields
            key = f['key']
            orig_val = dot_get(product, key)
            if f['type'] == 'bool':
                new_val = request.POST.get(f'field__{key}') == 'on'
            elif f['type'] == 'number':
                raw = request.POST.get(f'field__{key}', '')
                try:
                    if isinstance(orig_val, int) and raw.strip() != '':
                        new_val = int(raw)
                    else:
                        new_val = float(raw) if raw.strip() != '' else None
                except ValueError:
                    logger.error(f"Invalid number in field {key}: {raw}")
                    messages.error(request, f'Nieprawidłowa liczba w polu {key}.')
                    return render(request, 'modules/product_edit.html', {
                        'module': module,
                        'product': product,
                        'editable': editable,
                        'field_categories': field_categories,
                        'item_id': item_id,
                    })
            else:
                new_val = request.POST.get(f'field__{key}', '')

            # Compare; if different, schedule for update
            if new_val != orig_val:
                logger.info(f"Field {key} changed from {orig_val} to {new_val}")
                changed_flat[key] = new_val

        if not changed_flat:
            logger.info(f"No changes detected for product {item_id}")
            messages.info(request, 'Brak zmian do zapisania.')
            return redirect('modules:detail', pk=module.pk)

        logger.info(f"Updating product {item_id} with changes: {changed_flat}")
        update_payload = unflatten(changed_flat)
        logger.info(f"Unflattened payload: {update_payload}")
        
        ok, msg = update_product(module.shop.base_url, module.shop.bearer_token, item_id, update_payload)
        if ok:
            logger.info(f"Successfully updated product {item_id}")
            messages.success(request, f'Zapisano zmiany produktu. {msg}')
            return redirect('modules:detail', pk=module.pk)
        
        logger.error(f"Failed to update product {item_id}: {msg}")
        messages.error(request, f'Błąd zapisu: {msg}')

    return render(request, 'modules/product_edit.html', {
        'module': module,
        'product': product,
        'editable': editable,
        'field_categories': field_categories,
        'item_id': item_id,
    })


@login_required
def product_edit_json(request: HttpRequest, pk: int, item_id: int):
    """JSON endpoint for modal editing.
    - GET: returns editable fields with current values
    - POST: expects JSON {"changes": {"a.b": value, ...}} and performs partial update
    """
    logger.info(f"JSON endpoint called for product {item_id}, method: {request.method}")
    
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        return JsonResponse({'ok': False, 'error': 'Only products module is editable.'}, status=400)

    api_path = resolve_path(module.resource, module.api_path_override) or 'products'
    product = fetch_item(module.shop.base_url, module.shop.bearer_token, api_path, item_id)
    if not product:
        logger.error(f"Failed to fetch product {item_id} for JSON endpoint")
        return JsonResponse({'ok': False, 'error': 'Nie udało się pobrać produktu.'}, status=502)

    columns = module.fields_config or []

    if request.method == 'GET':
        def field_meta(key: str, label: str) -> Tuple[str, str, Any, bool]:
            val = dot_get(product, key)
            if isinstance(val, bool):
                type_name = 'bool'
            elif isinstance(val, (int, float)):
                type_name = 'number'
            else:
                type_name = 'text'
            editable_flag = is_editable_product_field(key)
            return key, type_name, val, editable_flag

        editable = [
            {
                'key': f['key'],
                'label': f.get('label') or f['key'],
                'type': field_meta(f['key'], f.get('label') or f['key'])[1],
                'value': field_meta(f['key'], f.get('label') or f['key'])[2],
                'editable': field_meta(f['key'], f.get('label') or f['key'])[3],
            }
            for f in columns
        ]
        logger.info(f"Returning {len(editable)} editable fields for product {item_id}")
        return JsonResponse({'ok': True, 'editable': editable, 'item_id': item_id})

    # POST: apply changes
    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    changes = data.get('changes') or {}
    if not isinstance(changes, dict):
        logger.error(f"Invalid changes format: {type(changes)}")
        return JsonResponse({'ok': False, 'error': 'Invalid changes format.'}, status=400)

    logger.info(f"Processing changes for product {item_id}: {changes}")

    # Build typed changed map by comparing to original values
    changed_flat: Dict[str, Any] = {}
    for key, new_val in changes.items():
        if not is_editable_product_field(key):
            # Ignore non-editable incoming keys silently
            logger.debug(f"Ignoring non-editable field: {key}")
            continue
        orig_val = dot_get(product, key)
        
        # Special handling for ID fields - they should not be empty strings
        if key.endswith('_id') and new_val == '':
            logger.info(f"Skipping empty ID field: {key}")
            continue
        
        # Coerce types to match original
        if isinstance(orig_val, bool):
            coerced = bool(new_val)
        elif isinstance(orig_val, int):
            try:
                if new_val == '' or new_val is None:
                    # For integer fields, empty means None/null, not 0
                    coerced = None
                else:
                    coerced = int(new_val)
            except Exception as e:
                logger.error(f"Invalid integer for {key}: {new_val}, error: {e}")
                return JsonResponse({'ok': False, 'error': f'Nieprawidłowa liczba całkowita dla {key}.'}, status=400)
        elif isinstance(orig_val, float):
            try:
                if new_val == '' or new_val is None:
                    coerced = None
                else:
                    coerced = float(str(new_val).replace(',', '.'))
            except Exception as e:
                logger.error(f"Invalid float for {key}: {new_val}, error: {e}")
                return JsonResponse({'ok': False, 'error': f'Nieprawidłowa liczba dla {key}.'}, status=400)
        else:
            # Keep as string if not None, otherwise pass-through
            coerced = new_val if new_val is not None else ''

        if coerced != orig_val:
            logger.info(f"Field {key} will change from {orig_val} to {coerced}")
            changed_flat[key] = coerced

    if not changed_flat:
        logger.info(f"No changes detected for product {item_id}")
        return JsonResponse({'ok': True, 'message': 'Brak zmian.'})

    logger.info(f"Applying changes to product {item_id}: {changed_flat}")
    update_payload = unflatten(changed_flat)
    logger.info(f"Unflattened payload: {update_payload}")
    
    ok, msg = update_product(module.shop.base_url, module.shop.bearer_token, item_id, update_payload)
    if ok:
        logger.info(f"Successfully updated product {item_id} via JSON endpoint")
        return JsonResponse({'ok': True, 'message': f'Zapisano zmiany. {msg}'})
    
    logger.error(f"Failed to update product {item_id} via JSON endpoint: {msg}")
    return JsonResponse({'ok': False, 'error': msg}, status=502)


@login_required
def product_redirect_json(request: HttpRequest, pk: int, item_id: int):
    """Create a SEO redirect to a given product id for this module's shop.
    - GET: returns suggested target path and defaults
    - POST: expects {source_url: str, code?: int}
    """
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        return JsonResponse({'ok': False, 'error': 'Dostępne tylko dla modułu produktów.'}, status=400)

    # Build preview data
    if request.method == 'GET':
        target_preview = guess_product_path(module.shop, item_id)
        return JsonResponse({
            'ok': True,
            'product_id': item_id,
            'target_preview': target_preview,
            'default_code': 301,
        })

    # POST: create and sync redirect
    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    source_url = (data.get('source_url') or '').strip()
    try:
        code = int(data.get('code') or 301)
    except Exception:
        code = 301

    if not source_url:
        return JsonResponse({'ok': False, 'error': 'Podaj źródłowy URL.'}, status=400)

    # Create rule and save first (sync updates fields and remote_id)
    rule = RedirectRule(
        owner=request.user,
        shop=module.shop,
        rule_type=RedirectRule.RuleType.PRODUCT_TO_URL,
        product_id=int(item_id),
        source_url=source_url,
        target_url='',
        status_code=code,
        active=True,
    )
    rule.save()
    result = sync_redirect_rule(rule)

    if result.ok:
        return JsonResponse({'ok': True, 'message': result.message, 'source_url': result.source_url, 'target_url': result.target_url})
    return JsonResponse({'ok': False, 'error': result.message}, status=502)

# Create your views here.


@login_required
@require_http_methods(["GET"])
def module_data_json(request: HttpRequest, pk: int):
    """Return grid-friendly rows for a module. Used by spreadsheet UI.
    Only intended for products resource at the moment.
    Response: {ok, columns: [{key,label,editable,type}], rows: [{item_id, <key>: value, ...}]}
    """
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    api_path = resolve_path(module.resource, module.api_path_override)

    # Limit rows - allow fetching all products (0 = no limit)
    try:
        limit = int(request.GET.get('limit') or 0)
    except Exception:
        limit = 0
    # If limit specified, cap it at 10000 for safety
    if limit > 0:
        limit = min(limit, 10000)

    logger.info(f"Fetching data for module {pk}, limit: {limit}")

    # Columns: use configured fields; for products, fallback to recommended if empty
    columns_cfg = module.fields_config or []
    if module.resource == Module.Resource.PRODUCTS and not columns_cfg:
        rec = get_recommended_product_fields()
        columns_cfg = [{'key': f['key'], 'label': f.get('label', f['key'])} for f in rec]

    rows = fetch_rows(module.shop.base_url, module.shop.bearer_token, api_path, limit=limit) if api_path else []
    
    logger.info(f"Fetched {len(rows)} rows for module {pk}")

    # Try to detect item_id per row
    id_keys = ['product_id', 'id', 'product.id', 'product.product_id', 'productId', 'productID', 'id_product']
    out_rows: List[Dict[str, Any]] = []
    for row in rows:
        item: Dict[str, Any] = {}
        found_id = None
        for k in id_keys:
            found_id = dot_get(row, k)
            if found_id is not None and str(found_id).strip() != '':
                break
        if found_id is not None:
            item['item_id'] = found_id
        # Collect selected columns
        for col in columns_cfg:
            key = col.get('key')
            if not key:
                continue
            val = dot_get(row, key)
            # Normalize value for grid display
            if isinstance(val, (dict, list)):
                try:
                    item[key] = json.dumps(val, ensure_ascii=False)
                except Exception:
                    item[key] = str(val)
            else:
                item[key] = val
        out_rows.append(item)

    # Build columns meta with type + editable info
    def infer_type(key: str) -> str:
        for r in out_rows:
            if key in r and r[key] is not None:
                v = r[key]
                if isinstance(v, bool):
                    return 'bool'
                if isinstance(v, (int, float)):
                    return 'number'
                break
        return 'text'

    columns_meta: List[Dict[str, Any]] = []
    for col in columns_cfg:
        key = col.get('key')
        label = col.get('label') or key
        if not key:
            continue
        editable = is_editable_product_field(key) if module.resource == Module.Resource.PRODUCTS else False
        columns_meta.append({
            'key': key,
            'label': label,
            'editable': editable,
            'type': infer_type(key),
        })

    logger.info(f"Returning {len(out_rows)} rows with {len(columns_meta)} columns")
    return JsonResponse({'ok': True, 'columns': columns_meta, 'rows': out_rows, 'resource': module.resource})


@login_required
@require_http_methods(["POST"])
def products_bulk_update_json(request: HttpRequest, pk: int):
    """Apply bulk updates to multiple products.
    Payload: {rows: [{item_id: int, changes: {"dot.key": value, ...}}, ...]}
    Returns per-row result and a summary.
    """
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        return JsonResponse({'ok': False, 'error': 'Dostępne tylko dla modułu produktów.'}, status=400)

    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    rows = payload.get('rows') or []
    if not isinstance(rows, list) or not rows:
        return JsonResponse({'ok': False, 'error': 'Brak danych do aktualizacji.'}, status=400)

    # Allow updates only on configured fields
    allowed_keys = {f['key'] for f in (module.fields_config or []) if isinstance(f, dict) and f.get('key')}

    updated = 0
    failed = 0
    results: List[Dict[str, Any]] = []

    for entry in rows:
        item_id = entry.get('item_id')
        changes = entry.get('changes') or {}
        if not item_id or not isinstance(changes, dict):
            failed += 1
            results.append({'item_id': item_id, 'ok': False, 'error': 'Nieprawidłowy rekord.'})
            continue

        # Filter to allowed + editable fields
        filtered_changes: Dict[str, Any] = {}
        for k, v in changes.items():
            if allowed_keys and k not in allowed_keys:
                continue
            if not is_editable_product_field(k):
                continue
            filtered_changes[k] = v

        if not filtered_changes:
            results.append({'item_id': item_id, 'ok': True, 'message': 'Brak zmian lub pola readonly.'})
            continue

        # Fetch original product for type coercion and comparison
        api_path = resolve_path(module.resource, module.api_path_override) or 'products'
        product = fetch_item(module.shop.base_url, module.shop.bearer_token, api_path, item_id)
        if not product:
            failed += 1
            results.append({'item_id': item_id, 'ok': False, 'error': 'Nie udało się pobrać produktu z API.'})
            continue

        changed_flat: Dict[str, Any] = {}
        for key, new_val in filtered_changes.items():
            orig_val = dot_get(product, key)
            # ID-like fields should not be empty strings
            if key.endswith('_id') and new_val == '':
                continue
            # Coerce types based on original
            try:
                if isinstance(orig_val, bool):
                    coerced = bool(new_val)
                elif isinstance(orig_val, int):
                    coerced = None if new_val in (None, '') else int(new_val)
                elif isinstance(orig_val, float):
                    coerced = None if new_val in (None, '') else float(str(new_val).replace(',', '.'))
                else:
                    coerced = new_val if new_val is not None else ''
            except Exception:
                failed += 1
                results.append({'item_id': item_id, 'ok': False, 'error': f'Nieprawidłowa wartość dla pola {key}.'})
                coerced = None  # prevent Unbound
                break
            if coerced != orig_val:
                changed_flat[key] = coerced

        if not changed_flat:
            results.append({'item_id': item_id, 'ok': True, 'message': 'Brak zmian.'})
            continue

        ok, msg = update_product(module.shop.base_url, module.shop.bearer_token, item_id, unflatten(changed_flat))
        if ok:
            updated += 1
            results.append({'item_id': item_id, 'ok': True, 'message': msg})
        else:
            failed += 1
            results.append({'item_id': item_id, 'ok': False, 'error': msg})

    return JsonResponse({'ok': True, 'updated': updated, 'failed': failed, 'results': results})


@login_required
def product_promo_json(request: HttpRequest, pk: int, item_id: int):
    """Create a time-bound special offer (promotion) for a product.
    - GET: returns base price and default dates
    - POST: expects {mode: 'amount'|'percent', value: number, date_from: str, date_to: str}
    Uses Shoper's deprecated 'special_offer' fields which are still widely supported.
    """
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        return JsonResponse({'ok': False, 'error': 'Dostępne tylko dla modułu produktów.'}, status=400)

    api_path = resolve_path(module.resource, module.api_path_override) or 'products'
    product = fetch_item(module.shop.base_url, module.shop.bearer_token, api_path, item_id)
    if not product:
        return JsonResponse({'ok': False, 'error': 'Nie udało się pobrać produktu z API.'}, status=502)

    # Helper to format defaults
    from datetime import datetime, timedelta
    now = datetime.now()
    default_from = now.strftime('%Y-%m-%d 00:00:00')
    default_to = (now + timedelta(days=7)).strftime('%Y-%m-%d 23:59:59')

    if request.method == 'GET':
        price = dot_get(product, 'stock.price')
        return JsonResponse({
            'ok': True,
            'product_id': item_id,
            'base_price': price,
            'default_from': default_from,
            'default_to': default_to,
        })

    # POST: create promo
    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    mode = (data.get('mode') or '').strip().lower()
    try:
        value = float(str(data.get('value') or '0').replace(',', '.'))
    except Exception:
        value = 0.0
    date_from = (data.get('date_from') or default_from).strip()
    date_to = (data.get('date_to') or default_to).strip()

    if mode not in ('amount', 'percent'):
        return JsonResponse({'ok': False, 'error': 'Wybierz typ promocji (kwotowa lub procentowa).'}, status=400)
    if value <= 0:
        return JsonResponse({'ok': False, 'error': 'Wartość promocji musi być większa od 0.'}, status=400)

    base_price = dot_get(product, 'stock.price') or 0
    try:
        base_price = float(base_price)
    except Exception:
        base_price = 0.0

    if base_price <= 0:
        return JsonResponse({'ok': False, 'error': 'Brak prawidłowej ceny bazowej produktu.'}, status=400)

    if mode == 'percent':
        discount_amount = round(base_price * (value / 100.0), 2)
    else:
        discount_amount = round(value, 2)

    if discount_amount <= 0:
        return JsonResponse({'ok': False, 'error': 'Wyliczona kwota rabatu jest nieprawidłowa.'}, status=400)
    if discount_amount >= base_price:
        return JsonResponse({'ok': False, 'error': 'Kwota rabatu nie może być większa lub równa cenie bazowej.'}, status=400)

    # Include stock_id when available for clarity (condition_type=1 -> whole product)
    stock_id = dot_get(product, 'stock.stock_id')
    special_offer = {
        'discount': discount_amount,
        'discount_type': 2,           # amount, stable
        'condition_type': 1,          # whole product
        'date_from': date_from,
        'date_to': date_to,
    }
    if stock_id:
        try:
            special_offer['stocks'] = [int(stock_id)]
        except Exception:
            pass

    payload = { 'special_offer': special_offer }

    ok, msg = update_product(module.shop.base_url, module.shop.bearer_token, item_id, payload)
    if ok:
        return JsonResponse({'ok': True, 'message': f'Promocja utworzona. {msg}', 'discount_amount': discount_amount})
    return JsonResponse({'ok': False, 'error': msg}, status=502)


@login_required
@ensure_csrf_cookie
def product_duplicate_json(request: HttpRequest, pk: int, item_id: int):
    """Duplicate a product N times. Copies required fields plus all copyable fields
    that are active in the module's configuration. Generates new unique codes.
    - GET: returns base code/name and default options
    - POST: expects {count:int, code_prefix?:str, code_suffix?:str, add_index?:bool, index_start?:int, bump_name?:bool}
    """
    logger.info(f"product_duplicate_json called: method={request.method}, pk={pk}, item_id={item_id}, user={request.user}")
    
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        logger.warning(f"Module {pk} is not a products module: {module.resource}")
        return JsonResponse({'ok': False, 'error': 'Dostępne tylko dla modułu produktów.'}, status=400)

    api_path = resolve_path(module.resource, module.api_path_override) or 'products'
    logger.info(f"Using API path: {api_path}")
    
    product = fetch_item(module.shop.base_url, module.shop.bearer_token, api_path, item_id)
    if not product:
        logger.error(f"Failed to fetch product {item_id} from API")
        return JsonResponse({'ok': False, 'error': 'Nie udało się pobrać produktu z API.'}, status=502)
    
    # Log full product structure for debugging
    logger.info(f"Original product structure: {json.dumps(product, indent=2, ensure_ascii=False)[:2000]}...")

    # Helper to read translation values
    def get_pl(field: str):
        return dot_get(product, f'translations.pl_PL.{field}')

    base_code = dot_get(product, 'code') or dot_get(product, 'stock.code') or ''
    base_name = get_pl('name') or ''

    if request.method == 'GET':
        return JsonResponse({
            'ok': True,
            'product_id': item_id,
            'base_code': base_code,
            'base_name': base_name,
            'defaults': {
                'count': 2,
                'code_prefix': '',
                'code_suffix': '-copy',
                'add_index': True,
                'index_start': 1,
                'bump_name': True,
            }
        })

    # POST
    logger.info(f"Processing POST request for duplication")
    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
        logger.info(f"Parsed request data: {data}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    try:
        count = int(data.get('count') or 1)
    except Exception:
        count = 1
    count = max(1, min(count, 50))

    code_prefix = (data.get('code_prefix') or '').strip()
    code_suffix = (data.get('code_suffix') or '').strip()
    add_index = bool(data.get('add_index') if data.get('add_index') is not None else True)
    try:
        index_start = int(data.get('index_start') or 1)
    except Exception:
        index_start = 1
    bump_name = bool(data.get('bump_name') if data.get('bump_name') is not None else True)

    # Build copyable keys from module fields
    configured_keys = [f['key'] for f in (module.fields_config or []) if isinstance(f, dict) and f.get('key')]

    # Required fields per spec
    required_errors: List[str] = []
    category_id = dot_get(product, 'category_id')
    pkwiu = dot_get(product, 'pkwiu')
    stock_price = dot_get(product, 'stock.price')
    name_pl = base_name or ''
    active_pl = get_pl('active')
    if category_id is None:
        required_errors.append('category_id')
    if not (base_code or code_prefix or code_suffix or add_index):
        required_errors.append('code')
    if pkwiu is None:
        required_errors.append('pkwiu')
    try:
        stock_price_val = float(stock_price)
    except Exception:
        stock_price_val = 0.0
    if stock_price_val <= 0:
        required_errors.append('stock.price')
    if not name_pl:
        required_errors.append('translations.pl_PL.name')
    if active_pl is None:
        active_pl = True

    if required_errors:
        return JsonResponse({'ok': False, 'error': f'Brak wymaganych pól do duplikacji: {", ".join(required_errors)}'}, status=400)

    # Get type from original product (default to 0 if missing)
    product_type = dot_get(product, 'type') or 0

    def build_code(i: int) -> str:
        idx = ''
        if add_index:
            idx = f"-{index_start + i}"
        # If original has no code, fallback to name-based slugish code
        base = base_code or (name_pl.replace(' ', '-').lower()[:16] or 'prod')
        return f"{code_prefix}{base}{code_suffix}{idx}"

    def safe_copy_key(dst: Dict[str, Any], key: str, value: Any):
        # Only copy editable keys to avoid system fields
        if is_editable_product_field(key):
            # Assign into nested dict
            cur = dst
            parts = [p for p in key.split('.') if p]
            for j, part in enumerate(parts):
                if j == len(parts) - 1:
                    cur[part] = value
                else:
                    if part not in cur or not isinstance(cur[part], dict):
                        cur[part] = {}
                    cur = cur[part]

    created = 0
    failed = 0
    results: List[Dict[str, Any]] = []

    # Pre-collect values to copy from configured keys
    for copy_idx in range(count):
        new_code = build_code(copy_idx)
        payload: Dict[str, Any] = {
            'type': product_type,  # Copy from original
            'category_id': category_id,
            'code': new_code,
            'pkwiu': pkwiu,
            'stock': {
                'price': stock_price_val,
                'active': True,  # Force stock to be active
                'default': True,  # Make it default stock
            },
            'translations': {
                'pl_PL': {
                    'name': f"{name_pl}{(' ' + str(index_start + copy_idx)) if bump_name else ''}",
                    'active': bool(active_pl),
                }
            }
        }

        # Always copy stock.additional_codes when present (treated as required in some configs)
        try:
            add_codes = dot_get(product, 'stock.additional_codes')
            if isinstance(add_codes, dict) and add_codes:
                payload.setdefault('stock', {})['additional_codes'] = add_codes
        except Exception:
            pass

        # Helpful defaults: copy tax_id/unit_id if present on source
        for opt_key in ('tax_id', 'unit_id'):
            val = dot_get(product, opt_key)
            if val is not None:
                payload[opt_key] = val
                
        # Copy important stock fields that might be required
        # Note: Don't copy availability_id from configured fields - we handle it specially
        stock_required_fields = ['active', 'default', 'calculated_availability_id']
        for field in stock_required_fields:
            val = dot_get(product, f'stock.{field}')
            if val is not None:
                payload.setdefault('stock', {})[field] = val
        
        # Handle availability_id specially - only set if explicitly present and not null
        availability_id = dot_get(product, 'stock.availability_id')
        if availability_id is not None and availability_id != '':
            payload.setdefault('stock', {})['availability_id'] = availability_id
        
        # Copy essential product level fields that might be required for visibility
        essential_fields = ['group_id', 'currency_id']
        for field in essential_fields:
            val = dot_get(product, field)
            if val is not None:
                payload[field] = val
                
        # Copy optional product level fields 
        optional_fields = ['bestseller', 'newproduct', 'in_loyalty']
        for field in optional_fields:
            val = dot_get(product, field)
            if val is not None:
                payload[field] = val

        # Copy any additional stock fields present in product and configured
        # plus stock.additional_codes when available
        stock_fields = [k for k in configured_keys if k.startswith('stock.')]
        for k in stock_fields:
            val = dot_get(product, k)
            if val is not None:
                safe_copy_key(payload, k, val)

        # Copy translations fields in configured keys for pl_PL
        trans_fields = [k for k in configured_keys if k.startswith('translations.pl_PL.')]
        for k in trans_fields:
            # Skip name/active (already set)
            if k.endswith('.name') or k.endswith('.active'):
                continue
            val = dot_get(product, k)
            if val is not None:
                safe_copy_key(payload, k, val)

        # Copy other configured keys (non readonly) — do not overwrite 'code'
        for k in configured_keys:
            if k.startswith('stock.') or k.startswith('translations.'):
                continue
            if k == 'code':
                continue
            val = dot_get(product, k)
            if val is not None:
                safe_copy_key(payload, k, val)

        # Try create; if code conflict occurs, auto-bump code with incremental suffix
        logger.info(f"Attempting to create product {copy_idx + 1}/{count}")
        logger.info(f"Payload keys: {list(payload.keys())}")
        logger.info(f"Stock keys: {list(payload.get('stock', {}).keys())}")
        logger.info(f"Full payload: {json.dumps(payload, indent=2, ensure_ascii=False)[:1500]}...")
        ok, msg, new_id = create_product(module.shop.base_url, module.shop.bearer_token, payload)
        logger.info(f"Create product result: ok={ok}, msg={msg}, new_id={new_id}")
        
        if not ok and isinstance(msg, str):
            lower = msg.lower()
            # Check for various code conflict indicators from API response
            conflict = (
                ('code' in lower and ('istnieje' in lower or 'exist' in lower)) or 
                'już istnieje' in lower or
                'already exists' in lower or
                'already in use' in lower or
                'duplicate' in lower or
                ('wartość' in lower and 'istnieje' in lower) or  # Polish Shoper API message
                ('value' in lower and 'already' in lower and 'exist' in lower)
            )
            logger.info(f"Checking for code conflict in message: '{msg}', conflict detected: {conflict}")
            if conflict:
                logger.info(f"Code conflict detected, attempting to bump code for product {copy_idx + 1}")
                bumped = False
                for bump_idx in range(1, 15):
                    payload['code'] = f"{new_code}-{bump_idx+1}"
                    logger.info(f"Retry with bumped code: {payload['code']}")
                    ok, msg, new_id = create_product(module.shop.base_url, module.shop.bearer_token, payload)
                    if ok:
                        bumped = True
                        logger.info(f"Successfully created with bumped code: {payload['code']}")
                        break
                if not bumped:
                    # Try a random short suffix to avoid collisions
                    import random, string
                    suffix = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
                    payload['code'] = f"{new_code}-{suffix}"
                    logger.info(f"Final retry with random suffix: {payload['code']}")
                    ok, msg, new_id = create_product(module.shop.base_url, module.shop.bearer_token, payload)

        if ok:
            created += 1
            # Fetch the newly created product and prepare a grid row snapshot
            new_row: Dict[str, Any] | None = None
            try:
                new_item = fetch_item(module.shop.base_url, module.shop.bearer_token, api_path, new_id)
                if new_item:
                    row_map: Dict[str, Any] = {'item_id': new_id}
                    for col in (module.fields_config or []):
                        key = col.get('key')
                        if not key:
                            continue
                        val = dot_get(new_item, key)
                        # Keep arrays and simple values as-is for Tabulator
                        # Only serialize complex nested objects
                        if isinstance(val, list):
                            # Keep simple arrays (like categories, collections) as arrays
                            row_map[key] = val
                        elif isinstance(val, dict):
                            # Serialize complex objects to JSON string
                            try:
                                row_map[key] = json.dumps(val, ensure_ascii=False)
                            except Exception:
                                row_map[key] = str(val)
                        else:
                            row_map[key] = val
                    new_row = row_map
            except Exception:
                new_row = None

            results.append({'ok': True, 'product_id': new_id, 'code': payload.get('code', new_code), 'row': new_row})
        else:
            failed += 1
            logger.warning(f"Failed to create product {copy_idx + 1}: {msg}")
            results.append({'ok': False, 'error': msg, 'code': payload.get('code', new_code)})

    logger.info(f"Duplication completed: created={created}, failed={failed}")
    return JsonResponse({'ok': True, 'created': created, 'failed': failed, 'results': results})


@login_required
@require_http_methods(["DELETE"])
def product_delete_json(request: HttpRequest, pk: int, item_id: int):
    """Delete a single product.
    - DELETE: removes the product from Shoper
    """
    logger.info(f"product_delete_json called for product {item_id}, module {pk}")
    
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        return JsonResponse({'ok': False, 'error': 'Dostępne tylko dla modułu produktów.'}, status=400)
    
    ok, msg = delete_product(module.shop.base_url, module.shop.bearer_token, item_id)
    
    if ok:
        logger.info(f"Successfully deleted product {item_id}")
        return JsonResponse({'ok': True, 'message': msg})
    
    logger.error(f"Failed to delete product {item_id}: {msg}")
    return JsonResponse({'ok': False, 'error': msg}, status=502)


@login_required
@require_http_methods(["POST"])
def products_bulk_delete_json(request: HttpRequest, pk: int):
    """Delete multiple products in bulk.
    Payload: {product_ids: [int, int, ...]}
    Returns per-product result and a summary.
    """
    logger.info(f"products_bulk_delete_json called for module {pk}")
    
    module = get_object_or_404(Module, pk=pk, owner=request.user)
    if module.resource != Module.Resource.PRODUCTS:
        return JsonResponse({'ok': False, 'error': 'Dostępne tylko dla modułu produktów.'}, status=400)
    
    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)
    
    product_ids = payload.get('product_ids') or []
    if not isinstance(product_ids, list) or not product_ids:
        return JsonResponse({'ok': False, 'error': 'Brak produktów do usunięcia.'}, status=400)
    
    deleted = 0
    failed = 0
    results: List[Dict[str, Any]] = []
    
    logger.info(f"Deleting {len(product_ids)} products")
    
    for product_id in product_ids:
        try:
            product_id = int(product_id)
        except Exception:
            failed += 1
            results.append({'product_id': product_id, 'ok': False, 'error': 'Nieprawidłowe ID produktu.'})
            continue
        
        ok, msg = delete_product(module.shop.base_url, module.shop.bearer_token, product_id)
        
        if ok:
            deleted += 1
            results.append({'product_id': product_id, 'ok': True, 'message': msg})
        else:
            failed += 1
            results.append({'product_id': product_id, 'ok': False, 'error': msg})
    
    logger.info(f"Bulk delete completed: deleted={deleted}, failed={failed}")
    return JsonResponse({'ok': True, 'deleted': deleted, 'failed': failed, 'results': results})
