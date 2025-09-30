from typing import Optional, Tuple, Dict, Any, List
from urllib.parse import urljoin, urlparse
import requests

from modules.shoper import build_rest_roots, auth_headers, extract_items, _try_get_json


def post_redirect(base_url: str, token: str, payloads: List[dict]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Try to create redirect via Shoper REST.
    We will try multiple payload shapes since public docs may vary.
    Returns (success, message, json_response)
    """
    last_error = 'Brak odpowiedzi z API redirectów.'
    for root in build_rest_roots(base_url):
        endpoint_candidates = ['redirects']
        lowered_root = root.lower()
        if 'rest' in lowered_root:
            # REST API expects /redirects; fallback do /seo/redirects jeśli istnieje alias
            endpoint_candidates = ['redirects', 'seo/redirects']
        else:
            # Avoid /seo/redirects on /webapi/api/ paths as it causes Core BugTracker Error
            if '/webapi/api/' not in lowered_root:
                endpoint_candidates.append('seo/redirects')
            # Nie próbuj /redirects/insert na ścieżkach zawierających "api/" (powoduje bugtrackera)
            if 'api/' not in lowered_root:
                endpoint_candidates.append('redirects/insert')

        for endpoint in endpoint_candidates:
            url = urljoin(root, endpoint)
            for data in payloads:
                try:
                    resp = requests.post(url, json=data, headers=auth_headers(token), timeout=12)
                    body = (resp.text or '')[:500]
                    if not (200 <= resp.status_code < 300):
                        last_error = f"HTTP {resp.status_code}: {body} @ {url}"
                        continue

                    parsed_json: Optional[Any] = None
                    try:
                        parsed_json = resp.json()
                    except Exception:
                        parsed_json = None

                    redirect_id: Optional[str] = None
                    if isinstance(parsed_json, dict):
                        for key in ('redirect_id', 'id', 'uuid', 'result', 'data'):
                            val = parsed_json.get(key)
                            if isinstance(val, (int, str)) and str(val).strip():
                                redirect_id = str(val).strip()
                                break
                    elif isinstance(parsed_json, int):
                        redirect_id = str(parsed_json)
                    else:
                        text_val = body.strip()
                        if text_val.isdigit():
                            redirect_id = text_val

                    if redirect_id:
                        payload_debug = {
                            'url': url,
                            'payload': data,
                            'status': resp.status_code,
                            'redirect_id': redirect_id,
                        }
                        if isinstance(parsed_json, dict):
                            parsed_json.setdefault('_debug', {})
                            parsed_json['_debug'].update(payload_debug)
                            parsed_json.setdefault('redirect_id', redirect_id)
                            return True, f"OK {resp.status_code}", parsed_json
                        return True, f"OK {resp.status_code}", {'redirect_id': redirect_id, '_debug': payload_debug}

                    last_error = f"HTTP {resp.status_code} (brak ID) @ {url}: {body}"
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e} @ {url}"

    return False, last_error, None


def build_payloads(
    source_url: str,
    code: int = 301,
    *,
    target_url: str = '',
    target_type: int = 0,
    target_object_id: Optional[int] = None,
    lang_id: Optional[int] = None,
) -> List[dict]:
    """Return candidate payload shapes for the redirects endpoint.

    We emit multiple payload variants because different Shoper instances expect slightly
    different field names. The first payload follows the official documentation.
    """

    payloads: List[Dict[str, Any]] = []

    # Primary documented payload
    documented: Dict[str, Any] = {
        'route': source_url,
        'type': target_type,
    }
    if target_object_id is not None and target_type != 0:
        documented['object_id'] = target_object_id
    if lang_id is not None:
        documented['lang_id'] = lang_id
    if target_type == 0 and target_url:
        documented['target'] = target_url
    payloads.append(documented)

    # Variant including HTTP code when allowed
    documented_with_code = dict(documented)
    documented_with_code['http_code'] = code
    if target_type == 0 and target_url:
        documented_with_code.setdefault('target', target_url)
    payloads.append(documented_with_code)

    # Legacy naming fallbacks used in some installations
    if target_type == 0:
        if target_url:
            payloads.append({'source': source_url, 'target': target_url, 'http_code': code})
            payloads.append({'old_url': source_url, 'new_url': target_url, 'code': code})
            payloads.append({'from': source_url, 'to': target_url, 'code': code})
    else:
        # For non-URL targets (product, category, etc.), don't include 'target' field
        # as per Shoper API docs - only use 'object_id' and 'type'
        base = {
            'source': source_url,
            'type': target_type,
        }
        if target_object_id is not None:
            base['object_id'] = target_object_id
        # DO NOT add 'target' for non-URL redirects (type != 0)
        base['http_code'] = code
        payloads.append(base)

    # Deduplicate while preserving order
    seen: List[str] = []
    unique: List[Dict[str, Any]] = []
    for entry in payloads:
        key = repr(sorted(entry.items()))
        if key in seen:
            continue
        seen.append(key)
        unique.append(entry)
    return unique


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


def parse_remote_redirect(
    item: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[str], Optional[int], Optional[int]]:
    """Return (source_url, target_url, status_code, remote_id, target_type, target_object_id)."""
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
    obj_type_raw = item.get('type') or item.get('object_type')
    obj_type_str = str(obj_type_raw).lower() if obj_type_raw is not None else ''
    if not target and prod_id:
        target = f"/product/{prod_id}"
    if not target and cat_id:
        target = f"/category/{cat_id}"
    if not target and obj_id and obj_type_str:
        if 'product' in obj_type_str:
            target = f"/product/{obj_id}"
        elif 'category' in obj_type_str:
            target = f"/category/{obj_id}"

    # Code and id
    code = item.get('http_code') or item.get('code') or item.get('status')
    rid = item.get('id') or item.get('redirect_id') or item.get('uuid')
    try:
        code = int(code) if code is not None else None
    except Exception:
        code = None
    # Determine target_type/object_id in accordance with REST docs
    target_type: Optional[int] = None
    target_object_id: Optional[int] = None
    if obj_type_raw is not None:
        try:
            target_type = int(obj_type_raw)
        except Exception:
            target_type = None
    if target_type is None:
        # try to infer from string representation
        if obj_type_str:
            if 'product' in obj_type_str:
                target_type = 1
            elif 'category' in obj_type_str:
                target_type = 2
            elif 'producer' in obj_type_str:
                target_type = 3
            elif 'info' in obj_type_str:
                target_type = 4
    if obj_id is not None:
        try:
            target_object_id = int(obj_id)
        except Exception:
            target_object_id = None
    return (
        source,
        target,
        code,
        str(rid) if rid is not None else None,
        target_type,
        target_object_id,
    )


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


def was_redirect_created(
    base_url: str,
    token: str,
    source_url: str,
    target_url: str,
    *,
    target_type: Optional[int] = None,
    target_object_id: Optional[int] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Verify by listing if a redirect with given source/target (or metadata) exists."""
    want_src = _norm_path(source_url)
    want_tgt = _norm_path(target_url)
    items = list_redirects(base_url, token, limit=500)
    for it in items:
        src, tgt, _, rid, remote_type, remote_obj = parse_remote_redirect(it)
        if _norm_path(src) != want_src:
            continue

        same_target = False
        if want_tgt and _norm_path(tgt) == want_tgt:
            same_target = True
        elif target_type is not None and remote_type == target_type:
            if target_object_id is None or remote_obj == target_object_id:
                same_target = True

        if same_target:
            return True, it
    return False, None
