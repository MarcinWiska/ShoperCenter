import csv
import io
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from django.utils.text import slugify

from shops.models import Shop

from .forms import RedirectImportUploadForm, RedirectRuleForm
from .importer import RedirectImportError, parse_redirects_csv
from .models import RedirectRule
from .helpers import guess_product_path, guess_category_path
from .services import sync_redirect_rule, delete_redirect_rule_remote
from .shoper_redirects import list_redirects, parse_remote_redirect, _norm_path


IMPORT_SESSION_KEY = 'seo_redirect_imports'


def _get_import_store(request: HttpRequest) -> Dict[str, Dict[str, Any]]:
    store = request.session.get(IMPORT_SESSION_KEY)
    if isinstance(store, dict):
        return store
    return {}


def _store_import_preview(request: HttpRequest, payload: Dict[str, Any]) -> str:
    token = uuid.uuid4().hex
    store = _get_import_store(request)
    store[token] = payload
    request.session[IMPORT_SESSION_KEY] = store
    request.session.modified = True
    return token


def _load_import_preview(request: HttpRequest, token: str) -> Optional[Dict[str, Any]]:
    store = _get_import_store(request)
    payload = store.get(token)
    if not payload:
        return None
    if payload.get('owner_id') != request.user.id:
        return None
    return payload


def _delete_import_preview(request: HttpRequest, token: str) -> None:
    store = _get_import_store(request)
    if token in store:
        del store[token]
        request.session[IMPORT_SESSION_KEY] = store
        request.session.modified = True


class RedirectRuleListView(LoginRequiredMixin, ListView):
    model = RedirectRule
    template_name = 'seo_redirects/rule_list.html'
    context_object_name = 'rules'

    def get_queryset(self):
        return RedirectRule.objects.filter(owner=self.request.user).select_related('shop')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['shops'] = Shop.objects.filter(owner=self.request.user)
        ctx['import_upload_url'] = reverse('seo_redirects:import_upload')
        ctx['import_sample_url'] = reverse('seo_redirects:import_sample')
        ctx['export_all_url'] = reverse('seo_redirects:export')
        return ctx


@login_required
def download_redirect_import_sample(request: HttpRequest) -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['rule_type', 'source_url', 'product_id', 'category_id', 'target_url', 'status_code', 'active', 'comment'])
    writer.writerow([
        'url_to_url',
        '/stara-strona',
        '',
        '',
        '/nowa-strona',
        301,
        1,
        'Przykładowe przekierowanie URL → URL',
    ])
    writer.writerow([
        'product_to_url',
        '/przekieruj/promocja',
        12345,
        '',
        '',
        301,
        1,
        'Produkt ID → URL; target_url zostanie domyślnie ustawiony na /product/ID',
    ])
    writer.writerow([
        'category_to_url',
        '/kolekcja/wiosna',
        '',
        678,
        '/nowa-kolekcja/wiosna-2024',
        302,
        1,
        'Kategoria ID → URL',
    ])

    csv_content = buffer.getvalue()
    response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="redirects_import_sample.csv"'
    return response


@login_required
def export_redirects_csv(request: HttpRequest) -> HttpResponse:
    shop_id = request.GET.get('shop')
    rules = RedirectRule.objects.filter(owner=request.user).select_related('shop').order_by('shop__name', 'source_url')
    filename = 'seo_redirects.csv'

    shop: Optional[Shop] = None
    if shop_id:
        shop = get_object_or_404(Shop, pk=shop_id, owner=request.user)
        rules = rules.filter(shop=shop)
        slug = slugify(shop.name) or f'shop-{shop.id}'
        filename = f'seo_redirects_{slug}.csv'
    else:
        filename = 'seo_redirects_all.csv'

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'shop',
        'rule_type',
        'source_url',
        'product_id',
        'category_id',
        'target_url',
        'status_code',
        'active',
        'target_type',
        'target_object_id',
        'remote_id',
        'last_sync_status',
        'created_at',
        'updated_at',
    ])

    for rule in rules:
        writer.writerow([
            rule.shop.name,
            rule.rule_type,
            rule.source_url,
            rule.product_id or '',
            rule.category_id or '',
            rule.target_url,
            rule.status_code,
            1 if rule.active else 0,
            rule.target_type,
            rule.target_object_id or '',
            rule.remote_id or '',
            rule.last_sync_status or '',
            rule.created_at.isoformat() if rule.created_at else '',
            rule.updated_at.isoformat() if rule.updated_at else '',
        ])

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # UTF-8 BOM for Excel compatibility
    response.write(buffer.getvalue())
    return response


class RedirectImportUploadView(LoginRequiredMixin, FormView):
    template_name = 'seo_redirects/import_upload.html'
    form_class = RedirectImportUploadForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['sample_url'] = reverse('seo_redirects:import_sample')
        return ctx

    def form_valid(self, form):
        shop = form.cleaned_data['shop']
        csv_file = form.cleaned_data['csv_file']
        sync_immediately = form.cleaned_data['sync_immediately']
        filename = getattr(csv_file, 'name', 'import.csv') or 'import.csv'

        try:
            parse_result = parse_redirects_csv(csv_file)
        except RedirectImportError as exc:
            form.add_error('csv_file', str(exc))
            return self.form_invalid(form)

        payload = {
            'owner_id': self.request.user.id,
            'shop_id': shop.id,
            'shop_name': shop.name,
            'sync_immediately': bool(sync_immediately),
            'filename': filename,
            'uploaded_at': timezone.now().isoformat(),
            'preview': parse_result.to_session_payload(),
        }
        token = _store_import_preview(self.request, payload)
        messages.info(
            self.request,
            f'Plik zawiera {parse_result.valid_rows} poprawnych rekordów (łącznie {parse_result.total_rows}). Zweryfikuj szczegóły i potwierdź import.',
        )
        return redirect('seo_redirects:import_preview', token=token)


class RedirectImportPreviewView(LoginRequiredMixin, TemplateView):
    template_name = 'seo_redirects/import_preview.html'

    def dispatch(self, request: HttpRequest, *args, **kwargs):
        self.import_token = kwargs.get('token')
        self.import_payload = _load_import_preview(request, self.import_token)
        if not self.import_payload:
            messages.error(request, 'Sesja importu wygasła lub jest nieprawidłowa.')
            return redirect('seo_redirects:import_upload')
        return super().dispatch(request, *args, **kwargs)

    def _get_shop(self) -> Shop:
        return get_object_or_404(Shop, pk=self.import_payload['shop_id'], owner=self.request.user)

    def _clone_rows(self) -> List[Dict[str, Any]]:
        rows = []
        preview = self.import_payload.get('preview') or {}
        for raw in preview.get('rows', []):
            row = {
                'index': raw.get('index'),
                'rule_type': raw.get('rule_type'),
                'source_url': raw.get('source_url'),
                'target_url': raw.get('target_url'),
                'product_id': raw.get('product_id'),
                'category_id': raw.get('category_id'),
                'status_code': raw.get('status_code'),
                'active': raw.get('active', True),
                'generated_target': raw.get('generated_target', False),
                'errors': list(raw.get('errors', [])),
                'warnings': list(raw.get('warnings', [])),
                'raw': raw.get('raw', {}),
                'is_valid': bool(raw.get('is_valid')), 
            }
            rows.append(row)
        return rows

    def _attach_existing_info(self, rows: List[Dict[str, Any]], shop: Shop) -> None:
        rules = RedirectRule.objects.filter(owner=self.request.user, shop=shop)
        by_source: Dict[str, List[RedirectRule]] = {}
        by_product: Dict[int, List[RedirectRule]] = {}
        by_category: Dict[int, List[RedirectRule]] = {}

        for rule in rules:
            if rule.source_url:
                by_source.setdefault(rule.source_url.lower(), []).append(rule)
            if rule.product_id is not None:
                by_product.setdefault(int(rule.product_id), []).append(rule)
            if rule.category_id is not None:
                by_category.setdefault(int(rule.category_id), []).append(rule)

        for row in rows:
            existing: Optional[RedirectRule] = None
            src = (row.get('source_url') or '').lower()
            if src and src in by_source:
                existing = by_source[src][0]
                if 'Istnieje już przekierowanie z tego samego source_url w tym sklepie.' not in row['warnings']:
                    row['warnings'].append('Istnieje już przekierowanie z tego samego source_url w tym sklepie.')

            if row.get('rule_type') == RedirectRule.RuleType.PRODUCT_TO_URL and row.get('product_id') not in (None, ''):
                pid = int(row['product_id'])
                if pid in by_product:
                    if existing is None:
                        existing = by_product[pid][0]
                    if 'Istnieje już przekierowanie dla tego ID produktu.' not in row['warnings']:
                        row['warnings'].append('Istnieje już przekierowanie dla tego ID produktu.')

            if row.get('rule_type') == RedirectRule.RuleType.CATEGORY_TO_URL and row.get('category_id') not in (None, ''):
                cid = int(row['category_id'])
                if cid in by_category:
                    if existing is None:
                        existing = by_category[cid][0]
                    if 'Istnieje już przekierowanie dla tej kategorii.' not in row['warnings']:
                        row['warnings'].append('Istnieje już przekierowanie dla tej kategorii.')

            if existing:
                row['existing_rule'] = {
                    'id': existing.pk,
                    'rule_type': existing.rule_type,
                    'source_url': existing.source_url,
                    'target_url': existing.target_url,
                    'status_code': existing.status_code,
                }
            else:
                row['existing_rule'] = None

            row['select_default'] = row['is_valid'] and row['existing_rule'] is None
            if row['warnings']:
                row['warnings'] = list(dict.fromkeys(row['warnings']))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        shop = self._get_shop()
        rows = self._clone_rows()
        self._attach_existing_info(rows, shop)

        preview = self.import_payload.get('preview') or {}
        ctx.update({
            'shop': shop,
            'rows': rows,
            'import_token': self.import_token,
            'stats': {
                'total': preview.get('total_rows', len(rows)),
                'valid': preview.get('valid_rows', 0),
                'invalid': preview.get('invalid_rows', 0),
            },
            'sync_immediately': bool(self.import_payload.get('sync_immediately')),
            'filename': self.import_payload.get('filename', 'import.csv'),
            'uploaded_at': self.import_payload.get('uploaded_at'),
        })
        return ctx

    def post(self, request: HttpRequest, *args, **kwargs):
        action = request.POST.get('action')
        if action == 'cancel':
            _delete_import_preview(request, self.import_token)
            messages.info(request, 'Import CSV został anulowany.')
            return redirect('seo_redirects:list')

        selected_indexes: Set[int] = set()
        for raw in request.POST.getlist('selected'):
            try:
                selected_indexes.add(int(raw))
            except (TypeError, ValueError):
                continue

        if not selected_indexes:
            messages.error(request, 'Zaznacz przynajmniej jeden rekord do zaimportowania.')
            return self.get(request, *args, **kwargs)

        shop = self._get_shop()
        preview_rows = self.import_payload.get('preview', {}).get('rows', [])
        rows_to_import = [row for row in preview_rows if row.get('index') in selected_indexes]

        if not rows_to_import:
            messages.error(request, 'Nie znaleziono wybranych rekordów do importu.')
            return self.get(request, *args, **kwargs)

        result = self._import_rows(rows_to_import, shop, bool(self.import_payload.get('sync_immediately')))
        _delete_import_preview(request, self.import_token)

        summary = f"Zaimportowano {result['imported']} z {len(rows_to_import)} zaznaczonych rekordów."
        if result['skipped']:
            summary += f" Pominięto: {result['skipped']}."
        if result['errors']:
            summary += f" Błędy: {result['errors']}."
        if result['sync_errors']:
            summary += f" Ostrzeżenia synchronizacji: {result['sync_errors']}."

        if result['errors'] or result['sync_errors']:
            messages.warning(request, summary)
        else:
            messages.success(request, summary)

        for entry in result['details'][:20]:
            status = entry['status']
            if status == 'error':
                messages.error(request, entry['message'])
            elif status == 'sync_error':
                messages.warning(request, entry['message'])
            elif status == 'skipped':
                messages.info(request, entry['message'])

        return redirect('seo_redirects:list')

    def _import_rows(self, rows: List[Dict[str, Any]], shop: Shop, sync_immediately: bool) -> Dict[str, Any]:
        imported = 0
        skipped = 0
        errors = 0
        sync_errors = 0
        details: List[Dict[str, Any]] = []

        for row in rows:
            if not row.get('is_valid'):
                skipped += 1
                details.append({
                    'status': 'skipped',
                    'message': f"Pominięto wiersz {row.get('index')} – zawiera błędy walidacji.",
                })
                continue

            status, message = self._create_rule(row, shop, sync_immediately)
            if status in {'created', 'synced'}:
                imported += 1
            elif status == 'skipped':
                skipped += 1
            elif status == 'sync_error':
                imported += 1
                sync_errors += 1
            elif status == 'updated':
                imported += 1
            else:
                errors += 1
            details.append({'status': status, 'message': message})

        return {
            'imported': imported,
            'skipped': skipped,
            'errors': errors,
            'sync_errors': sync_errors,
            'details': details,
        }

    def _update_existing_rule(self, rule: RedirectRule, row: Dict[str, Any], sync_immediately: bool) -> Tuple[str, str]:
        # Update core attributes based on incoming row
        updated_fields: List[str] = []
        source_url = _norm_path(row.get('source_url') or '')
        target_url = _norm_path(row.get('target_url') or '')
        status_code = int(row.get('status_code') or 301)
        active = bool(row.get('active', True))
        rule_type = row.get('rule_type') or rule.rule_type

        product_id = row.get('product_id')
        category_id = row.get('category_id')

        if product_id not in (None, ''):
            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                product_id = None
        else:
            product_id = None

        if category_id not in (None, ''):
            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                category_id = None
        else:
            category_id = None

        def set_attr(attr: str, value: Any) -> None:
            if getattr(rule, attr) != value:
                setattr(rule, attr, value)
                updated_fields.append(attr)

        set_attr('rule_type', rule_type)
        set_attr('source_url', source_url)
        set_attr('target_url', target_url)
        set_attr('status_code', status_code)
        set_attr('active', active)

        if rule_type == RedirectRule.RuleType.PRODUCT_TO_URL:
            if product_id is None:
                return 'error', f'Nie udało się zaktualizować przekierowania #{rule.pk}: brak ID produktu.'
            set_attr('product_id', product_id)
            set_attr('category_id', None)
            set_attr('target_type', RedirectRule.TargetType.PRODUCT)
            set_attr('target_object_id', product_id)
        elif rule_type == RedirectRule.RuleType.CATEGORY_TO_URL:
            if category_id is None:
                return 'error', f'Nie udało się zaktualizować przekierowania #{rule.pk}: brak ID kategorii.'
            set_attr('category_id', category_id)
            set_attr('product_id', None)
            set_attr('target_type', RedirectRule.TargetType.CATEGORY)
            set_attr('target_object_id', category_id)
        else:
            set_attr('product_id', None)
            set_attr('category_id', None)
            set_attr('target_type', RedirectRule.TargetType.OWN)
            set_attr('target_object_id', None)

        if updated_fields:
            rule.save(update_fields=list(dict.fromkeys(updated_fields)))

        if sync_immediately:
            try:
                sync_result = sync_redirect_rule(rule)
            except Exception as exc:
                return 'sync_error', f'Zaktualizowano #{rule.pk}, ale synchronizacja nie powiodła się: {exc}'

            if sync_result.ok:
                return 'synced', f'Zaktualizowano i zsynchronizowano przekierowanie #{rule.pk}: {rule.source_url}.'
            return 'sync_error', f'Zaktualizowano #{rule.pk}, ale synchronizacja zwróciła błąd: {sync_result.message}'

        if updated_fields:
            return 'updated', f'Zaktualizowano istniejące przekierowanie #{rule.pk}.'
        return 'skipped', f'Pominięto – przekierowanie #{rule.pk} już istnieje i nie wymaga zmian.'

    def _create_rule(self, row: Dict[str, Any], shop: Shop, sync_immediately: bool) -> Tuple[str, str]:
        source_url = row.get('source_url') or ''
        target_url = row.get('target_url') or ''
        rule_type = row.get('rule_type') or RedirectRule.RuleType.URL_TO_URL
        status_code = int(row.get('status_code') or 301)
        active = bool(row.get('active', True))
        product_id = row.get('product_id')
        category_id = row.get('category_id')

        if product_id not in (None, ''):
            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                product_id = None
        else:
            product_id = None

        if category_id not in (None, ''):
            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                category_id = None
        else:
            category_id = None

        existing = RedirectRule.objects.filter(owner=self.request.user, shop=shop, source_url=source_url).first()
        if existing:
            status, message = self._update_existing_rule(existing, row, sync_immediately)
            return status, message

        if rule_type == RedirectRule.RuleType.PRODUCT_TO_URL and product_id is not None:
            conflict = RedirectRule.objects.filter(
                owner=self.request.user,
                shop=shop,
                rule_type=RedirectRule.RuleType.PRODUCT_TO_URL,
                product_id=product_id,
            ).first()
            if conflict:
                return 'skipped', f'Pominięto – produkt {product_id} ma już przypisane przekierowanie #{conflict.pk}.'

        if rule_type == RedirectRule.RuleType.CATEGORY_TO_URL and category_id is not None:
            conflict = RedirectRule.objects.filter(
                owner=self.request.user,
                shop=shop,
                rule_type=RedirectRule.RuleType.CATEGORY_TO_URL,
                category_id=category_id,
            ).first()
            if conflict:
                return 'skipped', f'Pominięto – kategoria {category_id} ma już przypisane przekierowanie #{conflict.pk}.'

        rule = RedirectRule(
            owner=self.request.user,
            shop=shop,
            rule_type=rule_type,
            source_url=source_url,
            target_url=target_url,
            status_code=status_code,
            active=active,
        )

        if rule_type == RedirectRule.RuleType.PRODUCT_TO_URL:
            rule.product_id = product_id
            rule.target_type = RedirectRule.TargetType.PRODUCT
            rule.target_object_id = product_id
        elif rule_type == RedirectRule.RuleType.CATEGORY_TO_URL:
            rule.category_id = category_id
            rule.target_type = RedirectRule.TargetType.CATEGORY
            rule.target_object_id = category_id
        else:
            rule.target_type = RedirectRule.TargetType.OWN
            rule.target_object_id = None

        try:
            rule.save()
        except Exception as exc:
            return 'error', f'Błąd zapisu przekierowania ({source_url} → {target_url}): {exc}'

        if sync_immediately:
            try:
                sync_result = sync_redirect_rule(rule)
            except Exception as exc:  # Defensive
                return 'sync_error', f'Zapisano #{rule.pk}, ale synchronizacja z API nie powiodła się: {exc}'

            if sync_result.ok:
                return 'synced', f'Zapisano i zsynchronizowano przekierowanie #{rule.pk}: {source_url} → {sync_result.target_url or target_url}.'
            return 'sync_error', f'Zapisano #{rule.pk}, ale synchronizacja zwróciła błąd: {sync_result.message}'

        return 'created', f'Zapisano przekierowanie #{rule.pk}: {source_url} → {target_url}.'


class RedirectRuleCreateView(LoginRequiredMixin, CreateView):
    model = RedirectRule
    form_class = RedirectRuleForm
    template_name = 'seo_redirects/rule_form.html'
    success_url = reverse_lazy('seo_redirects:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.owner = self.request.user
        response = super().form_valid(form)
        self._sync_and_notify()
        return response

    def _sync_and_notify(self):
        result = sync_redirect_rule(self.object)
        if result.level == 'success':
            messages.success(self.request, result.message)
        elif result.level == 'warning':
            messages.warning(self.request, result.message)
        else:
            messages.error(self.request, result.message)


class RedirectRuleUpdateView(LoginRequiredMixin, UpdateView):
    model = RedirectRule
    form_class = RedirectRuleForm
    template_name = 'seo_redirects/rule_form.html'
    success_url = reverse_lazy('seo_redirects:list')

    def get_queryset(self):
        return RedirectRule.objects.filter(owner=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        self._sync_and_notify()
        return response

    def _sync_and_notify(self):
        result = sync_redirect_rule(self.object)
        if result.level == 'success':
            messages.success(self.request, result.message)
        elif result.level == 'warning':
            messages.warning(self.request, result.message)
        else:
            messages.error(self.request, result.message)


class RedirectRuleDeleteView(LoginRequiredMixin, DeleteView):
    model = RedirectRule
    template_name = 'seo_redirects/rule_confirm_delete.html'
    success_url = reverse_lazy('seo_redirects:list')

    def get_queryset(self):
        return RedirectRule.objects.filter(owner=self.request.user)

    def post(self, request: HttpRequest, *args, **kwargs):
        """Override post to handle both GET confirmation and POST deletion."""
        import sys
        print(f"\n{'='*80}", file=sys.stderr, flush=True)
        print(f"POST METHOD CALLED!", file=sys.stderr, flush=True)
        print(f"{'='*80}\n", file=sys.stderr, flush=True)
        return self.delete(request, *args, **kwargs)

    def delete(self, request: HttpRequest, *args, **kwargs):
        import sys
        self.object = self.get_object()
        print(f"\n{'='*80}", file=sys.stderr, flush=True)
        print(f"DELETE REQUEST: ID={self.object.id}, source={self.object.source_url}, remote_id={self.object.remote_id}", file=sys.stderr, flush=True)
        print(f"{'='*80}\n", file=sys.stderr, flush=True)
        
        # Najpierw próbujemy usunąć z API Shopera
        result = delete_redirect_rule_remote(self.object)
        print(f"\n{'='*80}", file=sys.stderr, flush=True)
        print(f"DELETE API RESULT: ok={result.ok}, level={result.level}, message={result.message}", file=sys.stderr, flush=True)
        print(f"{'='*80}\n", file=sys.stderr, flush=True)
        
        # Usuwamy z lokalnej bazy niezależnie od wyniku API
        # (żeby nie pozostały "zombie" rekordy które i tak nie istnieją w Shoperze)
        response = super().delete(request, *args, **kwargs)
        print(f"\n{'='*80}", file=sys.stderr, flush=True)
        print(f"DELETE DB: Deleted from database successfully", file=sys.stderr, flush=True)
        print(f"{'='*80}\n", file=sys.stderr, flush=True)
        
        # Informujemy użytkownika o wyniku operacji na API
        if result.ok:
            messages.success(request, f'Przekierowanie usunięte z aplikacji i Shopera. {result.message}')
        else:
            if result.level == 'error':
                messages.error(request, f'Usunięto z aplikacji, ale wystąpił błąd podczas usuwania z Shopera: {result.message}')
            else:
                messages.warning(request, f'Usunięto z aplikacji. {result.message}')
        
        return response


@login_required
def sync_rule(request, pk):
    rule = get_object_or_404(RedirectRule, pk=pk, owner=request.user)
    result = sync_redirect_rule(rule)
    if result.level == 'success':
        messages.success(request, result.message)
    elif result.level == 'warning':
        messages.warning(request, result.message)
    else:
        messages.error(request, result.message)
    return redirect('seo_redirects:list')


@login_required
def pull_redirects(request, shop_id: int):
    from shops.models import Shop
    shop = get_object_or_404(Shop, pk=shop_id, owner=request.user)
    items = list_redirects(shop.base_url, shop.bearer_token)
    created = 0
    updated = 0
    skipped = 0
    found = len(items)
    for it in items:
        source, target, code, rid, target_type, target_object_id = parse_remote_redirect(it)
        if not source:
            skipped += 1
            continue

        if target_type is not None and target_type < 0:
            target_type = None

        # Fallbacks dla docelowych ścieżek
        if (not target or target in {'', '/product/', '/category/'}):
            if target_type == RedirectRule.TargetType.PRODUCT and target_object_id:
                target = guess_product_path(shop, target_object_id)
            elif target_type == RedirectRule.TargetType.CATEGORY and target_object_id:
                target = guess_category_path(shop, target_object_id)

        if not target:
            skipped += 1
            continue
        # Normalize paths
        nsrc = _norm_path(source)
        ntgt = _norm_path(target)
        # If target is generic fallback, try refine using object info
        if (ntgt.startswith('/product/') or ntgt.startswith('/category/')):
            t_raw2 = it.get('type') or it.get('object_type')
            t2 = (str(t_raw2).lower() if t_raw2 is not None else '')
            obj2 = it.get('object_id') or it.get('objectId')
            try:
                obj2 = int(obj2) if obj2 is not None else None
            except Exception:
                obj2 = None
            if obj2:
                better = None
                if 'prod' in t2:
                    better = guess_product_path(shop, obj2)
                elif 'cat' in t2:
                    better = guess_category_path(shop, obj2)
                if better:
                    ntgt = _norm_path(better)

        # Try to match by remote_id first, then by (shop, source_url, target_url) with basic normalization
        rule = None
        if rid:
            rule = RedirectRule.objects.filter(owner=request.user, shop=shop, remote_id=rid).first()
        if not rule:
            alt_src = {nsrc}
            if nsrc != '/':
                alt_src.update({nsrc.rstrip('/'), nsrc.rstrip('/') + '/'})
            alt_tgt = {ntgt}
            if ntgt != '/':
                alt_tgt.update({ntgt.rstrip('/'), ntgt.rstrip('/') + '/'})
            rule = RedirectRule.objects.filter(
                owner=request.user,
                shop=shop,
                source_url__in=alt_src,
                target_url__in=alt_tgt,
            ).first()
        if rule:
            # update
            changed_fields: List[str] = []
            if code and rule.status_code != code:
                rule.status_code = code
                changed_fields.append('status_code')
            if rid and rule.remote_id != rid:
                rule.remote_id = rid
                changed_fields.append('remote_id')
            if target_type is not None and rule.target_type != target_type:
                rule.target_type = target_type
                changed_fields.append('target_type')
            if rule.target_object_id != target_object_id:
                rule.target_object_id = target_object_id
                changed_fields.append('target_object_id')
            # Keep legacy helpers in sync for UI
            if target_type == RedirectRule.TargetType.PRODUCT:
                if target_object_id and rule.product_id != target_object_id:
                    rule.product_id = target_object_id
                    changed_fields.append('product_id')
                if rule.rule_type != RedirectRule.RuleType.PRODUCT_TO_URL:
                    rule.rule_type = RedirectRule.RuleType.PRODUCT_TO_URL
                    changed_fields.append('rule_type')
            elif target_type == RedirectRule.TargetType.CATEGORY:
                if target_object_id and rule.category_id != target_object_id:
                    rule.category_id = target_object_id
                    changed_fields.append('category_id')
                if rule.rule_type != RedirectRule.RuleType.CATEGORY_TO_URL:
                    rule.rule_type = RedirectRule.RuleType.CATEGORY_TO_URL
                    changed_fields.append('rule_type')
            else:
                if rule.rule_type != RedirectRule.RuleType.URL_TO_URL:
                    rule.rule_type = RedirectRule.RuleType.URL_TO_URL
                    changed_fields.append('rule_type')
            if rule.target_url != ntgt:
                rule.target_url = ntgt
                changed_fields.append('target_url')
            if changed_fields:
                rule.save(update_fields=list(dict.fromkeys(changed_fields)))
                updated += 1
        else:
            # Infer rule type from Shoper target type
            rule_type = RedirectRule.RuleType.URL_TO_URL
            extra: Dict[str, Any] = {
                'target_type': target_type or RedirectRule.TargetType.OWN,
                'target_object_id': target_object_id,
            }
            if target_type == RedirectRule.TargetType.PRODUCT and target_object_id:
                rule_type = RedirectRule.RuleType.PRODUCT_TO_URL
                extra['product_id'] = target_object_id
            elif target_type == RedirectRule.TargetType.CATEGORY and target_object_id:
                rule_type = RedirectRule.RuleType.CATEGORY_TO_URL
                extra['category_id'] = target_object_id

            RedirectRule.objects.create(
                owner=request.user,
                shop=shop,
                rule_type=rule_type,
                source_url=nsrc,
                target_url=ntgt,
                status_code=(code or 301),
                remote_id=(rid or ''),
                **extra,
            )
            created += 1
    messages.success(request, f'Pobrano przekierowania z API (znaleziono {found}): utworzono {created}, zaktualizowano {updated}, pominięto {skipped}.')
    if skipped and not created and not updated and items:
        try:
            sample_keys = list(items[0].keys())[:10]
            messages.info(request, f'Podgląd kluczy z API (pierwszy rekord): {", ".join(sample_keys)}')
        except Exception:
            pass
    return redirect('seo_redirects:list')


@login_required
def generate_seo_redirects(request, shop_id: int):
    """Widok do generowania przyjaznych SEO URL dla produktów"""
    from shops.models import Shop
    from .seo_url_generator import generate_redirects_for_products
    
    shop = get_object_or_404(Shop, pk=shop_id, owner=request.user)
    
    if request.method == 'POST':
        # Pobierz listę ID produktów z formularza
        product_ids_raw = request.POST.get('product_ids', '')
        
        # Parse ID produktów (oddzielone przecinkami, spacjami lub nowymi liniami)
        product_ids = []
        for part in product_ids_raw.replace('\n', ',').replace(' ', ',').split(','):
            part = part.strip()
            if part.isdigit():
                product_ids.append(int(part))
        
        if not product_ids:
            messages.error(request, 'Nie podano żadnych ID produktów.')
            return redirect('seo_redirects:generate_seo_redirects', shop_id=shop_id)
        
        # Generuj przekierowania
        results = generate_redirects_for_products(shop, product_ids)
        
        # Utwórz reguły przekierowań
        created = 0
        errors = 0
        skipped = 0
        
        for result in results:
            if result['status'] == 'success':
                # Sprawdź czy przekierowanie już istnieje
                existing = RedirectRule.objects.filter(
                    shop=shop,
                    source_url=result['source_url']
                ).first()
                
                if existing:
                    skipped += 1
                    messages.warning(
                        request, 
                        f"Pominięto {result['product_name']} - przekierowanie już istnieje: {result['source_url']}"
                    )
                    continue
                
                # Utwórz nową regułę - WAŻNE: typ to PRODUCT_TO_URL, nie URL_TO_URL
                rule = RedirectRule.objects.create(
                    owner=request.user,
                    shop=shop,
                    rule_type=RedirectRule.RuleType.PRODUCT_TO_URL,
                    product_id=result['product_id'],
                    source_url=result['source_url'],
                    target_url=result['target_url'],
                    target_type=RedirectRule.TargetType.PRODUCT,
                    target_object_id=result['product_id'],
                    status_code=301,
                    active=True
                )
                
                # Synchronizuj z API Shopera
                from .services import sync_redirect_rule
                sync_result = sync_redirect_rule(rule)
                
                if sync_result.ok:
                    created += 1
                else:
                    errors += 1
                    messages.warning(
                        request,
                        f"Utworzono regułę dla {result['product_name']}, ale synchronizacja z API nie powiodła się: {sync_result.message}"
                    )
            else:
                errors += 1
                messages.error(
                    request,
                    f"Błąd dla produktu #{result['product_id']}: {result['message']}"
                )
        
        # Podsumowanie
        if created > 0:
            messages.success(
                request,
                f'Utworzono {created} przekierowań SEO. Pominięto: {skipped}, Błędy: {errors}'
            )
        elif skipped > 0 and errors == 0:
            messages.info(request, f'Wszystkie przekierowania już istnieją ({skipped} pominiętych).')
        else:
            messages.error(request, f'Nie utworzono żadnych przekierowań. Błędy: {errors}')
        
        return redirect('seo_redirects:list')
    
    # GET - pokaż formularz
    from django.shortcuts import render
    return render(request, 'seo_redirects/generate_seo_form.html', {
        'shop': shop
    })


@login_required
def preview_seo_url(request, shop_id: int):
    """API endpoint do podglądu wygenerowanego SEO URL dla produktu"""
    from shops.models import Shop
    from .seo_url_generator import generate_seo_url_for_product, get_product_shoper_url

    shop = get_object_or_404(Shop, pk=shop_id, owner=request.user)
    
    product_id = request.GET.get('product_id')
    if not product_id or not product_id.isdigit():
        return JsonResponse({'error': 'Nieprawidłowe ID produktu'}, status=400)
    
    product_id = int(product_id)
    
    try:
        seo_url = generate_seo_url_for_product(shop, product_id)
        shoper_url = get_product_shoper_url(shop, product_id)
        
        if not seo_url:
            return JsonResponse({'error': 'Nie udało się wygenerować SEO URL'}, status=400)
        
        return JsonResponse({
            'success': True,
            'product_id': product_id,
            'seo_url': seo_url,
            'shoper_url': shoper_url or 'brak',
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Błąd podglądu SEO URL dla produktu {product_id}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def propose_seo_redirects(request, shop_id: int):
    """Widok pokazujący propozycje SEO URL dla wszystkich produktów w sklepie"""
    from shops.models import Shop
    from modules.shoper import fetch_rows
    from .seo_url_generator import generate_redirects_for_products
    from django.shortcuts import render
    from .models import CategoryHierarchy
    from .hierarchy_builder import refresh_hierarchy_for_shop
    
    shop = get_object_or_404(Shop, pk=shop_id, owner=request.user)
    
    import logging
    logger = logging.getLogger(__name__)
    
    # ZAWSZE odśwież hierarchię przed generowaniem (bo mogły się zmienić kategorie w Shoper)
    logger.info(f"Odświeżanie hierarchii dla sklepu {shop.name}...")
    try:
        created, updated = refresh_hierarchy_for_shop(shop)
        hierarchy_count = created + updated
        logger.info(f"✅ Hierarchia odświeżona: {created} utworzonych, {updated} zaktualizowanych")
        
        if created > 0:
            messages.success(request, f'Znaleziono {created} nowych kategorii.')
        if updated > 0 and created == 0:
            messages.info(request, f'Hierarchia zaktualizowana ({updated} kategorii).')
            
    except Exception as e:
        logger.error(f"❌ Błąd podczas odświeżania hierarchii: {e}")
        messages.warning(request, f'Nie udało się odświeżyć hierarchii kategorii: {e}')
        hierarchy_count = CategoryHierarchy.objects.filter(shop=shop).count()
    
    if request.method == 'POST':
        # Pobierz zaznaczone produkty z wybranymi kategoriami
        # Format: selected_products = ['30_24', '31_16'] gdzie format to product_id_category_id
        selected_products = request.POST.getlist('selected_products')
        
        if not selected_products:
            messages.error(request, 'Nie wybrano żadnych produktów.')
            return redirect('seo_redirects:propose_seo_redirects', shop_id=shop_id)
        
        # Parsuj wybory: product_id_category_id lub product_id_all (dla wszystkich kategorii)
        products_with_categories = []
        for item in selected_products:
            parts = item.split('_')
            if len(parts) >= 2:
                pid = int(parts[0])
                if parts[1] == 'all':
                    # Wszystkie kategorie dla tego produktu
                    products_with_categories.append({'product_id': pid, 'category_id': 'all'})
                else:
                    # Konkretna kategoria
                    cid = int(parts[1])
                    products_with_categories.append({'product_id': pid, 'category_id': cid})
        
        if not products_with_categories:
            messages.error(request, 'Nieprawidłowe dane wyboru.')
            return redirect('seo_redirects:propose_seo_redirects', shop_id=shop_id)
        
        # Generuj przekierowania dla wybranych produktów i kategorii
        from .seo_url_generator import generate_seo_url_for_product
        from modules.shoper import fetch_item
        
        # Pobierz cache kategorii raz
        all_categories_cache = fetch_rows(shop.base_url, shop.bearer_token, 'categories', limit=0)
        
        results = []
        for item in products_with_categories:
            pid = item['product_id']
            cid = item['category_id']
            
            if cid == 'all':
                # Wygeneruj dla wszystkich kategorii
                from .category_selection import generate_urls_for_all_categories
                product_data = fetch_item(shop.base_url, shop.bearer_token, 'products', pid)
                if product_data:
                    product_name = product_data.get('translations', {}).get('pl_PL', {}).get('name', '')
                    cat_urls = generate_urls_for_all_categories(shop, pid, product_name)
                    for cat_url in cat_urls:
                        results.append({
                            'status': 'success',
                            'product_id': pid,
                            'product_name': product_name,
                            'category_id': cat_url['category_id'],
                            'source_url': cat_url['seo_url'],
                            'target_url': f"/prod{pid}",
                        })
            else:
                # Konkretna kategoria
                seo_url = generate_seo_url_for_product(
                    shop, pid, 
                    selected_category_id=cid, 
                    all_categories_cache=all_categories_cache
                )
                if seo_url:
                    product_data = fetch_item(shop.base_url, shop.bearer_token, 'products', pid)
                    product_name = product_data.get('translations', {}).get('pl_PL', {}).get('name', '') if product_data else ''
                    results.append({
                        'status': 'success',
                        'product_id': pid,
                        'product_name': product_name,
                        'category_id': cid,
                        'source_url': seo_url,
                        'target_url': f"/prod{pid}",
                    })
        
        # Utwórz reguły przekierowań
        created = 0
        errors = 0
        skipped = 0
        
        for result in results:
            if result['status'] == 'success':
                # Sprawdź czy przekierowanie już istnieje (po source_url, nie product_id!)
                # Ten sam produkt może mieć wiele przekierowań (różne kategorie)
                existing = RedirectRule.objects.filter(
                    shop=shop,
                    source_url=result['source_url']
                ).first()
                
                if existing:
                    skipped += 1
                    logger.info(f"Pominięto: {result['source_url']} - już istnieje (ID: {existing.id})")
                    continue
                
                logger.info(f"Tworzenie przekierowania: {result['source_url']} → {result['target_url']}")
                
                # Utwórz nową regułę
                rule = RedirectRule.objects.create(
                    owner=request.user,
                    shop=shop,
                    rule_type=RedirectRule.RuleType.PRODUCT_TO_URL,
                    product_id=result['product_id'],
                    source_url=result['source_url'],
                    target_url=result['target_url'],
                    target_type=RedirectRule.TargetType.PRODUCT,
                    target_object_id=result['product_id'],
                    status_code=301,
                    active=True
                )
                
                # Synchronizuj z API Shopera
                from .services import sync_redirect_rule
                sync_result = sync_redirect_rule(rule)
                
                if sync_result.ok:
                    created += 1
                    logger.info(f"✅ Utworzono i zsynchronizowano: {result['source_url']}")
                else:
                    errors += 1
                    logger.error(f"❌ Błąd synchronizacji: {result['source_url']} - {sync_result.message}")
            else:
                errors += 1
                logger.error(f"❌ Błąd generowania URL dla produktu {result.get('product_id')}")
        
        # Podsumowanie
        if created > 0:
            messages.success(
                request,
                f'Utworzono {created} przekierowań SEO. Pominięto: {skipped}, Błędy: {errors}'
            )
        else:
            messages.warning(request, f'Nie utworzono żadnych nowych przekierowań. Pominięto: {skipped}, Błędy: {errors}')
        
        return redirect('seo_redirects:list')
    
    # GET - pobierz wszystkie produkty i wygeneruj propozycje
    try:
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Pobieranie produktów dla sklepu {shop.name}...")
        
        # Pobierz wszystkie produkty (bez limitu)
        products = fetch_rows(shop.base_url, shop.bearer_token, 'products', limit=0)
        
        logger.info(f"Pobrano {len(products)} produktów")
        
        if not products:
            messages.warning(request, 'Nie znaleziono produktów w sklepie.')
            return redirect('seo_redirects:list')
        
        # Pobierz ID produktów
        product_ids = []
        for p in products:
            pid = p.get('product_id') or p.get('id')
            if pid:
                product_ids.append(int(pid))
        
        logger.info(f"Generowanie propozycji dla {len(product_ids)} produktów...")
        
        # Generuj propozycje z informacją o kategoriach (max 50 produktów na raz dla wydajności)
        from .category_selection import get_product_categories_for_selection
        from .seo_url_generator import generate_seo_url_for_product
        
        # Pobierz wszystkie kategorie RAZ (cache dla wydajności)
        logger.info("Pobieranie listy wszystkich kategorii...")
        all_categories_cache = fetch_rows(shop.base_url, shop.bearer_token, 'categories', limit=0)
        logger.info(f"Pobrano {len(all_categories_cache)} kategorii do cache")
        
        proposals = []
        limit = min(50, len(product_ids))  # Limit 50 produktów na stronę
        
        logger.info(f"Przetwarzanie {limit} produktów...")
        
        for i, pid in enumerate(product_ids[:limit]):
            try:
                # Pobierz dane produktu (porównaj jako string bo API może zwracać string)
                product = next((p for p in products if str(p.get('product_id') or p.get('id')) == str(pid)), None)
                if not product:
                    logger.warning(f"Nie znaleziono danych produktu {pid}")
                    continue
                
                product_name = product.get('translations', {}).get('pl_PL', {}).get('name', product.get('name', ''))
                
                if not product_name:
                    logger.warning(f"Produkt {pid} nie ma nazwy")
                    continue
                
                # Pobierz kategorie produktu (użyj cache)
                categories = get_product_categories_for_selection(shop, pid, product, all_categories_cache)
                
                if not categories:
                    logger.warning(f"Produkt {pid} nie ma żadnych kategorii - pomijam")
                    continue
                
                # Wygeneruj URL dla każdej kategorii (użyj cache)
                category_options = []
                for cat in categories:
                    seo_url = generate_seo_url_for_product(
                        shop, 
                        pid, 
                        selected_category_id=cat['id'],
                        use_full_hierarchy=True,
                        all_categories_cache=all_categories_cache
                    )
                    if seo_url:
                        category_options.append({
                            'category_id': cat['id'],
                            'category_name': cat['name'],
                            'category_path': cat['path_display'],
                            'seo_url': seo_url
                        })
                
                if category_options:
                    proposals.append({
                        'product_id': pid,
                        'product_name': product_name,
                        'target_url': f"/prod{pid}",
                        'categories': category_options,
                        'has_multiple_categories': len(category_options) > 1
                    })
                
                if (i + 1) % 10 == 0:
                    logger.info(f"Przetworzono {i + 1}/{limit} produktów...")
                    
            except Exception as e:
                logger.error(f"Błąd dla produktu {pid}: {e}")
                continue
        
        # Sprawdź które już istnieją
        existing_redirects = {}
        for rule in RedirectRule.objects.filter(shop=shop, product_id__isnull=False):
            key = (rule.product_id, rule.source_url)
            existing_redirects[key] = True
        
        # Dodaj info o istniejących
        for proposal in proposals:
            for cat_opt in proposal['categories']:
                key = (proposal['product_id'], cat_opt['seo_url'])
                cat_opt['already_exists'] = key in existing_redirects
        
        logger.info(f"Wygenerowano propozycje dla {len(proposals)} produktów")
        
        return render(request, 'seo_redirects/propose_seo.html', {
            'shop': shop,
            'proposals': proposals,
            'total_products': len(products),
            'shown_count': len(proposals),
            'hierarchy_count': hierarchy_count,
        })
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Błąd podczas pobierania propozycji SEO: {e}")
        messages.error(request, f'Błąd: {str(e)}')
        return redirect('seo_redirects:list')


@login_required
def refresh_hierarchy(request, shop_id: int):
    """Odświeża hierarchię kategorii dla sklepu"""
    from shops.models import Shop
    from .models import CategoryHierarchy
    from .hierarchy_builder import refresh_hierarchy_for_shop
    
    shop = get_object_or_404(Shop, pk=shop_id, owner=request.user)
    
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Odświeżanie hierarchii dla sklepu {shop.name}...")
        created, updated = refresh_hierarchy_for_shop(shop)
        
        total = created + updated
        logger.info(f"✅ Hierarchia odświeżona: {created} utworzonych, {updated} zaktualizowanych")
        messages.success(request, f'Hierarchia kategorii odświeżona: {total} kategorii (nowych: {created}, zaktualizowanych: {updated})')
        
    except Exception as e:
        logger.error(f"❌ Błąd podczas odświeżania hierarchii: {e}")
        messages.error(request, f'Nie udało się odświeżyć hierarchii kategorii: {e}')
    
    return redirect('seo_redirects:propose_seo_redirects', shop_id=shop_id)
