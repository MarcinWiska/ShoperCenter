from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urljoin

import requests


RESOURCE_TO_PATH = {
    'products': 'products',
    'orders': 'orders',
    'categories': 'categories',
    'users': 'users',
    'producers': 'producers',
    'shippings': 'shippings',
    'payments': 'payments',
    'subscribers': 'subscribers',
    'taxes': 'taxes',
    'units': 'units',
}


def build_rest_roots(base_url: str) -> List[str]:
    """Generate likely REST roots (end with '/'). Prefer '/webapi/rest/'."""
    u = base_url.rstrip('/')
    lowered = u.lower()
    seen = set()
    roots: List[str] = []

    def add(candidate: str) -> None:
        if candidate not in seen:
            roots.append(candidate)
            seen.add(candidate)

    normalized_base = u + '/'

    # Prefer explicit API roots first
    if lowered.endswith('/webapi/rest'):
        add(normalized_base)
        add(u.rsplit('/', 1)[0] + '/')  # .../webapi/
    elif lowered.endswith('/webapi'):
        add(u + '/rest/')
        add(u + '/')
    elif lowered.endswith('/api/rest'):
        add(normalized_base)
        add(u.rsplit('/', 1)[0] + '/')  # .../api/
    elif lowered.endswith('/api'):
        add(u + '/rest/')
        add(u + '/')
    elif lowered.endswith('/rest'):
        add(normalized_base)

    # Generic guesses when base_url does not already include API segment
    if '/webapi/' not in lowered and not lowered.endswith('/webapi') and '/webapi/rest' not in lowered:
        add(u + '/webapi/rest/')
        add(u + '/webapi/')
    if '/api/' not in lowered and not lowered.endswith('/api') and '/api/rest' not in lowered:
        add(u + '/api/rest/')
        add(u + '/api/')
    if not lowered.endswith('/rest') and '/rest/' not in lowered:
        add(u + '/rest/')

    # Finally, fallback to the provided base itself
    add(normalized_base)

    return roots


def build_rest_url(base_url: str, path: str) -> str:
    root = build_rest_roots(base_url)[0]
    return urljoin(root, path.lstrip('/'))


def auth_headers(token: str) -> Dict[str, str]:
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
    }


def extract_items(payload: Any) -> List[Dict[str, Any]]:
    """Extract a list of dicts from various API envelope shapes (recursive)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        # Try common envelope keys (including 'redirects')
        for key in ['list', 'items', 'results', 'data', 'products', 'orders', 'redirects', 'records']:
            val = payload.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val
        # Recurse into nested dicts to find first list of dicts
        for v in payload.values():
            if isinstance(v, dict):
                got = extract_items(v)
                if got:
                    return got
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def flatten(obj: Any, prefix: str = '') -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            out.update(flatten(v, key))
    elif isinstance(obj, list):
        # For lists, do not explode indices; show as joined value
        out[prefix] = ','.join(str(x) for x in obj[:5]) if prefix else ','.join(str(x) for x in obj[:5])
    else:
        out[prefix] = obj
    return out


def _try_get_json(url: str, token: str, timeout: int = 12) -> Tuple[Optional[Any], Optional[str]]:
    try:
        resp = requests.get(url, headers=auth_headers(token), timeout=timeout)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code} for {url}"
        return resp.json(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e} for {url}"


def fetch_fields(base_url: str, token: str, path: str, limit: int = 20) -> List[str]:
    p = path.strip('/')
    data: Optional[Any] = None
    for root in build_rest_roots(base_url):
        candidates = [
            urljoin(root, p),
            urljoin(root, p + '/'),
            urljoin(root, p) + '?limit=20',
            urljoin(root, p + '/') + '?limit=20',
            urljoin(root, p) + '?page=1&limit=20',
        ]
        for url in candidates:
            data, _ = _try_get_json(url, token)
            if data is not None:
                break
        if data is not None:
            break
    if data is None:
        return []
    items = extract_items(data)
    if not items:
        return []
    flat_keys = set()
    for item in items[:limit]:
        flat = flatten(item)
        flat_keys.update(flat.keys())
    return sorted(flat_keys)


def fetch_rows(base_url: str, token: str, path: str, limit: int = 50) -> List[Dict[str, Any]]:
    p = path.strip('/')
    data: Optional[Any] = None
    for root in build_rest_roots(base_url):
        candidates = [
            urljoin(root, p) + f'?limit={limit}',
            urljoin(root, p + '/') + f'?limit={limit}',
            urljoin(root, p),
        ]
        for url in candidates:
            data, _ = _try_get_json(url, token)
            if data is not None:
                break
        if data is not None:
            break
    if data is None:
        return []
    items = extract_items(data)
    return items[:limit] if isinstance(items, list) else []


def resolve_path(resource: str, override: Optional[str]) -> Optional[str]:
    if override:
        return override
    return RESOURCE_TO_PATH.get(resource)
