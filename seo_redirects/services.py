"""Synchronization helpers for redirect rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

from .helpers import guess_product_path, guess_category_path
from .models import RedirectRule
from .shoper_redirects import (
    post_redirect,
    build_payloads,
    was_redirect_created,
    _norm_path,
    parse_remote_redirect,
)


@dataclass
class SyncResult:
    ok: bool
    level: str  # 'success', 'warning', 'error'
    message: str
    source_url: str = ''
    target_url: str = ''


def sync_redirect_rule(rule: RedirectRule) -> SyncResult:
    """Synchronize a redirect rule with the Shoper API and persist state."""
    shop = rule.shop

    # Resolve source URL
    source = (rule.source_url or '').strip()
    if not source:
        if rule.rule_type == RedirectRule.RuleType.PRODUCT_TO_URL and rule.product_id:
            source = guess_product_path(shop, rule.product_id)
        elif rule.rule_type == RedirectRule.RuleType.CATEGORY_TO_URL and rule.category_id:
            source = guess_category_path(shop, rule.category_id)
    source = _norm_path(source)
    if not source:
        return SyncResult(
            ok=False,
            level='error',
            message='Nie można ustalić Źródłowego URL — uzupełnij pole Źródłowy URL lub ID produktu/kategorii.',
        )

    # Resolve target URL and type based on rule type
    target_type = RedirectRule.TargetType.OWN  # Default to URL redirect
    target_object_id: Optional[int] = None
    target = (rule.target_url or '').strip()
    target = _norm_path(target)
    
    if rule.rule_type == RedirectRule.RuleType.PRODUCT_TO_URL:
        # This means: redirect FROM custom URL TO product
        if not rule.product_id:
            return SyncResult(
                ok=False,
                level='error',
                message='Dla reguły Product ID → URL wymagane jest ID produktu.',
            )
        # The target is a product, not a URL
        target_type = RedirectRule.TargetType.PRODUCT
        target_object_id = int(rule.product_id)
        # For product targets, API expects object_id, not target URL
        # But we store target_url for display purposes
        if not target:
            target = guess_product_path(shop, rule.product_id)
            target = _norm_path(target)
        
    elif rule.rule_type == RedirectRule.RuleType.CATEGORY_TO_URL:
        # This means: redirect FROM custom URL TO category
        if not rule.category_id:
            return SyncResult(
                ok=False,
                level='error',
                message='Dla reguły Category ID → URL wymagane jest ID kategorii.',
            )
        # The target is a category, not a URL
        target_type = RedirectRule.TargetType.CATEGORY
        target_object_id = int(rule.category_id)
        # For category targets, API expects object_id, not target URL
        # But we store target_url for display purposes
        if not target:
            target = guess_category_path(shop, rule.category_id)
            target = _norm_path(target)

    if not source:
        return SyncResult(
            ok=False,
            level='error',
            message='Nie można ustalić Źródłowego URL.',
        )

    payloads = build_payloads(
        source,
        rule.status_code,
        target_url=target if target_type == RedirectRule.TargetType.OWN else '',
        target_type=int(target_type),
        target_object_id=target_object_id,
        lang_id=1,  # Default Polish language
    )
    ok, msg, js = post_redirect(shop.base_url, shop.bearer_token, payloads)

    dbg_url = None
    if isinstance(js, dict):
        dbg = js.get('_debug')
        if isinstance(dbg, dict):
            dbg_url = dbg.get('url')

    status_text = msg if dbg_url is None else f"{msg} @ {dbg_url}"
    status_text = status_text[:200]

    rule.last_sync_status = status_text
    rule.last_sync_at = timezone.now()

    fields_to_update = ['last_sync_status', 'last_sync_at']

    if ok and isinstance(js, dict):
        rid = js.get('id') or js.get('redirect_id') or js.get('uuid')
        if rid is not None:
            rid = str(rid)
            if rule.remote_id != rid:
                rule.remote_id = rid
                fields_to_update.append('remote_id')

    if source and rule.source_url != source:
        rule.source_url = source
        fields_to_update.append('source_url')
    if target and rule.target_url != target:
        rule.target_url = target
        fields_to_update.append('target_url')
    if rule.target_type != int(target_type):
        rule.target_type = int(target_type)
        fields_to_update.append('target_type')
    if rule.target_object_id != target_object_id:
        rule.target_object_id = target_object_id
        fields_to_update.append('target_object_id')

    rule.save(update_fields=list(dict.fromkeys(fields_to_update)))

    if ok:
        exists, remote_item = was_redirect_created(
            shop.base_url,
            shop.bearer_token,
            source,
            target,
            target_type=int(target_type),
            target_object_id=target_object_id,
            remote_id=rule.remote_id,
        )
        if exists:
            if remote_item:
                r_src, r_tgt, _, _, r_type, r_obj = parse_remote_redirect(remote_item)
                updated_fields: list[str] = []
                if r_type == RedirectRule.TargetType.PRODUCT and (not r_tgt) and r_obj:
                    # Refresh storefront path for better preview when API omits it
                    guessed = guess_product_path(shop, r_obj)
                    if guessed:
                        r_tgt = guessed
                if r_type == RedirectRule.TargetType.CATEGORY and (not r_tgt) and r_obj:
                    guessed = guess_category_path(shop, r_obj)
                    if guessed:
                        r_tgt = guessed
                if r_tgt and rule.target_url != _norm_path(r_tgt):
                    rule.target_url = _norm_path(r_tgt)
                    updated_fields.append('target_url')
                if r_type is not None and rule.target_type != r_type:
                    rule.target_type = r_type
                    updated_fields.append('target_type')
                if r_obj is not None and rule.target_object_id != r_obj:
                    rule.target_object_id = r_obj
                    updated_fields.append('target_object_id')
                if updated_fields:
                    rule.save(update_fields=list(dict.fromkeys(updated_fields)))
            return SyncResult(
                ok=True,
                level='success',
                message=f'Zsynchronizowano przekierowanie. {msg}',
                source_url=source,
                target_url=target,
            )
        # API accepted but redirect not confirmed – warn
        suffix = f' @ {dbg_url}' if dbg_url else ''
        return SyncResult(
            ok=False,
            level='warning',
            message=f'API zwróciło {msg}{suffix}, ale nie znaleziono przekierowania na liście. Sprawdź wymagany format w swojej instancji Shopera.',
            source_url=source,
            target_url=target,
        )

    return SyncResult(
        ok=False,
        level='error',
        message=f'Błąd synchronizacji: {msg}',
        source_url=source,
        target_url=target,
    )
