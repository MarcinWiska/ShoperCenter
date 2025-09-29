from typing import Optional, Tuple, Dict, Any, List
from urllib.parse import urljoin, urlparse
import requests

from modules.shoper import build_rest_roots, auth_headers, extract_items, _try_get_json


def post_redirect(base_url: str, token: str, payloads: List[dict]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Try to create redirect via Shoper REST.
    We will try multiple payload shapes since public docs may vary.
    Returns (success, message, json_response)
    """
    for root in build_rest_roots(base_url):
        url = urljoin(root, 'redirects')
        for data in payloads:
            try:
                resp = requests.post(url, json=data, headers=auth_headers(token), timeout=12)
                if 200 <= resp.status_code < 300:
                    try:
                        js = resp.json()
                        # Attach debug info
                        if isinstance(js, dict):
                            js.setdefault('_debug', {})
                            js['_debug'].update({'url': url, 'payload': data, 'status': resp.status_code})
                        return True, f"OK {resp.status_code}", js
                    except Exception:
                        return True, f"OK {resp.status_code}", {'_debug': {'url': url, 'payload': data, 'status': resp.status_code, 'body': resp.text[:500]}}
                # Continue trying alternative shapes
                last = f"HTTP {resp.status_code}: {resp.text[:300]} @ {url}"
            except Exception as e:
                last = f"{type(e).__name__}: {e} @ {url}"
        # next root
    return False, last, None


def build_payloads(source_url: str, target_url: str, code: int = 301) -> List[dict]:
    """Return candidate payload shapes for redirects endpoint (without active flag)."""
    return [
        {"source": source_url, "target": target_url, "http_code": code},
        {"old_url": source_url, "new_url": target_url, "code": code},
        {"from": source_url, "to": target_url, "code": code},
    ]


def list_redirects(base_url: str, token: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Fetch existing redirects from Shopera. Returns list of dicts as-is from API."""
    for root in build_rest_roots(base_url):
        candidates = [
            urljoin(root, f"redirects?limit={limit}"),
            urljoin(root, "redirects"),
            urljoin(root, f"seo/redirects?limit={limit}"),
            urljoin(root, "seo/redirects"),
            urljoin(root, f"redirects/list?limit={limit}"),
        ]
        for url in candidates:
            data, _ = _try_get_json(url, token)
            if data is None:
                continue
            items = extract_items(data)
            if items:
                return items
    return []


def parse_remote_redirect(item: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    """Return (source_url, target_url, status_code, remote_id) parsed from remote item."""
    # Source
    source = (
        item.get('source') or item.get('old_url') or item.get('from') or
        item.get('url') or item.get('source_url') or item.get('prev_url') or item.get('from_url') or
        item.get('previous_url') or item.get('route')
    )
    # Target
    target = (
        item.get('target') or item.get('new_url') or item.get('to') or
        item.get('target_url') or item.get('redirect_url')
    )
    # If target missing, derive from object references
    prod_id = item.get('product_id') or item.get('productId') or item.get('target_product_id')
    cat_id = item.get('category_id') or item.get('categoryId') or item.get('target_category_id')
    obj_id = item.get('object_id') or item.get('objectId')
    obj_type = str(item.get('type') or item.get('object_type') or '').lower()
    if not target and prod_id:
        target = f"/product/{prod_id}"
    if not target and cat_id:
        target = f"/category/{cat_id}"
    if not target and obj_id and obj_type:
        if 'product' in obj_type:
            target = f"/product/{obj_id}"
        elif 'category' in obj_type:
            target = f"/category/{obj_id}"

    # Code and id
    code = item.get('http_code') or item.get('code') or item.get('status')
    rid = item.get('id') or item.get('redirect_id') or item.get('uuid')
    try:
        code = int(code) if code is not None else None
    except Exception:
        code = None
    return source, target, code, str(rid) if rid is not None else None


def _norm_path(url_like: Optional[str]) -> str:
    if not url_like:
        return ''
    s = str(url_like).strip()
    if s.startswith('http://') or s.startswith('https://'):
        try:
            p = urlparse(s)
            s = p.path or '/'
        except Exception:
            pass
    if not s.startswith('/'):
        s = '/' + s
    # Remove duplicate trailing slashes
    while len(s) > 1 and s.endswith('//'):
        s = s[:-1]
    return s


def was_redirect_created(base_url: str, token: str, source_url: str, target_url: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Verify by listing if a redirect with given source/target exists."""
    want_src = _norm_path(source_url)
    want_tgt = _norm_path(target_url)
    items = list_redirects(base_url, token, limit=500)
    for it in items:
        src, tgt, _, rid = parse_remote_redirect(it)
        if _norm_path(src) == want_src and _norm_path(tgt) == want_tgt:
            return True, it
    return False, None
