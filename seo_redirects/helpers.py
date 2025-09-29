"""Helper utilities for working with Shoper redirects."""

from __future__ import annotations

from typing import Optional

from modules.shoper import build_rest_roots, _try_get_json


def _ensure_path(value: str) -> str:
    """Normalize API-provided paths so they always start with a single slash."""
    if not value:
        return ''
    value = value.strip()
    if not value:
        return ''
    if not value.startswith('/'):
        value = '/' + value
    while value.endswith('//'):
        value = value[:-1]
    return value


def guess_product_path(shop, product_id: int) -> Optional[str]:
    """Return the best SEO path for a product id using the Shoper API."""
    for root in build_rest_roots(shop.base_url):
        url = f"{root}products/{product_id}"
        data, _ = _try_get_json(url, shop.bearer_token)
        if not isinstance(data, dict):
            continue
        # Try common direct keys first
        for key in ("seo_url", "seo", "url", "slug"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return _ensure_path(val)
        translations = data.get("translations")
        if isinstance(translations, dict):
            pl = translations.get("pl")
            if isinstance(pl, dict):
                for key in ("seo", "seo_url", "url", "slug", "name"):
                    val = pl.get(key)
                    if isinstance(val, str) and val.strip():
                        return _ensure_path(val)
    # Fallback if API gives no SEO path
    return f"/product/{product_id}"


def guess_category_path(shop, category_id: int) -> Optional[str]:
    """Return the best SEO path for a category id using the Shoper API."""
    for root in build_rest_roots(shop.base_url):
        url = f"{root}categories/{category_id}"
        data, _ = _try_get_json(url, shop.bearer_token)
        if not isinstance(data, dict):
            continue
        for key in ("seo_url", "seo", "url", "slug"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return _ensure_path(val)
        translations = data.get("translations")
        if isinstance(translations, dict):
            pl = translations.get("pl")
            if isinstance(pl, dict):
                for key in ("seo", "seo_url", "url", "slug", "name"):
                    val = pl.get(key)
                    if isinstance(val, str) and val.strip():
                        return _ensure_path(val)
    return f"/category/{category_id}"

