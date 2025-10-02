from typing import Any, Dict, List

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import RedirectRule
from .forms import RedirectRuleForm
from .helpers import guess_product_path, guess_category_path
from .services import sync_redirect_rule
from .shoper_redirects import list_redirects, parse_remote_redirect, _norm_path


class RedirectRuleListView(LoginRequiredMixin, ListView):
    model = RedirectRule
    template_name = 'seo_redirects/rule_list.html'
    context_object_name = 'rules'

    def get_queryset(self):
        return RedirectRule.objects.filter(owner=self.request.user).select_related('shop')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # shops for import buttons
        from shops.models import Shop
        ctx['shops'] = Shop.objects.filter(owner=self.request.user)
        return ctx


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
    from django.http import JsonResponse
    
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
