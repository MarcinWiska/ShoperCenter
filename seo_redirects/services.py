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

    # Resolve target URL
    target = (rule.target_url or '').strip()
    target = _norm_path(target)
    if rule.rule_type == RedirectRule.RuleType.PRODUCT_TO_URL:
        if not rule.product_id:
            return SyncResult(
                ok=False,
                level='error',
                message='Dla reguły Product ID → URL wymagane jest ID produktu.',
            )
        if not target:
            guess = guess_product_path(shop, rule.product_id)
            target = _norm_path(guess)
    elif rule.rule_type == RedirectRule.RuleType.CATEGORY_TO_URL:
        if not rule.category_id:
            return SyncResult(
                ok=False,
                level='error',
                message='Dla reguły Category ID → URL wymagane jest ID kategorii.',
            )
        if not target:
            guess = guess_category_path(shop, rule.category_id)
            target = _norm_path(guess)

    if not target:
        return SyncResult(
            ok=False,
            level='error',
            message='Nie można ustalić Docelowego URL — uzupełnij pole Docelowy URL lub ID produktu/kategorii.',
        )

    payloads = build_payloads(source, target, rule.status_code)
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

    rule.save(update_fields=list(dict.fromkeys(fields_to_update)))

    if ok:
        exists, _ = was_redirect_created(shop.base_url, shop.bearer_token, source, target)
        if exists:
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

