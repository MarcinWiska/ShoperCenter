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
        source, target, code, rid = parse_remote_redirect(it)
        if not source or not target:
            # Try to derive target from object type/id if missing
            t_raw = it.get('type') or it.get('object_type')
            t = (str(t_raw).lower() if t_raw is not None else '')
            obj_id = it.get('object_id') or it.get('objectId')
            try:
                obj_id = int(obj_id) if obj_id is not None else None
            except Exception:
                obj_id = None
            if not target and obj_id:
                guess = None
                if 'prod' in t:
                    guess = guess_product_path(shop, obj_id)
                elif 'cat' in t:
                    guess = guess_category_path(shop, obj_id)
                else:
                    # Try both
                    guess = guess_product_path(shop, obj_id)
                    if not guess or guess.startswith('/product/'):
                        guess = guess_category_path(shop, obj_id)
                target = guess
            # If nadal brak kluczowych danych – pomiń
            if not source or not target:
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
            changed = False
            if code and rule.status_code != code:
                rule.status_code = code
                changed = True
            if rid and rule.remote_id != rid:
                rule.remote_id = rid
                changed = True
            if changed:
                rule.save(update_fields=['status_code', 'remote_id'])
                updated += 1
        else:
            # Infer rule type from item
            t = str(it.get('type') or it.get('object_type') or '').lower()
            obj_id = it.get('object_id') or it.get('objectId')
            rule_type = RedirectRule.RuleType.URL_TO_URL
            extra = {}
            try:
                if obj_id is not None:
                    obj_id = int(obj_id)
            except Exception:
                obj_id = None
            if 'product' in t and obj_id:
                rule_type = RedirectRule.RuleType.PRODUCT_TO_URL
                extra['product_id'] = obj_id
            elif 'category' in t and obj_id:
                rule_type = RedirectRule.RuleType.CATEGORY_TO_URL
                extra['category_id'] = obj_id

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
