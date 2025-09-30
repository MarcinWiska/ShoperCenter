from typing import Dict, List, Any, Optional, Tuple, Union
from urllib.parse import urljoin
import json

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


def create_product(base_url: str, token: str, payload: Dict[str, Any]) -> Tuple[bool, str, Optional[int]]:
    """Create a new product.
    Tries multiple payload shapes. Returns (ok, message, new_id).
    """
    import logging
    logger = logging.getLogger(__name__)

    url = build_rest_url(base_url, "products")
    headers = auth_headers(token)
    headers['Content-Type'] = 'application/json'

    attempts: List[Tuple[Dict[str, Any], str]] = []
    attempts.append((payload, "POST plain"))
    attempts.append(({"product": payload}, "POST product envelope"))

    try:
        last_code = None
        last_text = ""
        for body, label in attempts:
            resp = requests.post(url, headers=headers, json=body, timeout=20)
            last_code = resp.status_code
            last_text = resp.text[:1000]
            logger.info(f"Create product {label} -> HTTP {resp.status_code}")
            logger.info(f"Response: {last_text}")
            if resp.status_code in (200, 201, 202):
                # Extract id from json or integer response
                new_id: Optional[int] = None
                try:
                    data = resp.json()
                    if isinstance(data, dict):
                        for key in ('id', 'product_id', 'result', 'created_id'):
                            if key in data:
                                try:
                                    new_id = int(data[key])
                                except Exception:
                                    pass
                                break
                    elif isinstance(data, int):
                        new_id = int(data)
                except Exception:
                    # ignore json errors
                    pass
                return True, "Produkt utworzony", new_id

            # Parse error
            try:
                data = resp.json()
                if isinstance(data, dict):
                    # Try to get detailed error message from Shoper API
                    error_msg = (
                        data.get('error_description') or 
                        data.get('error') or 
                        data.get('message') or 
                        data.get('errors') or 
                        str(data)
                    )
                else:
                    error_msg = str(data)
            except Exception:
                error_msg = last_text or f"HTTP {last_code}"

            # 4xx do not retry
            if resp.status_code in (400, 401, 403, 404, 422):
                return False, f"Błąd tworzenia: {error_msg}", None
        # all attempts failed
        return False, f"Nie udało się utworzyć produktu (HTTP {last_code})", None
    except requests.exceptions.Timeout:
        return False, "Przekroczono czas oczekiwania na odpowiedź API", None
    except requests.exceptions.ConnectionError:
        return False, "Błąd połączenia z API", None
    except Exception as e:
        return False, f"Nieoczekiwany błąd: {type(e).__name__}: {e}", None


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


def dot_get(data: Any, path: str) -> Any:
    """Get nested value from dict/list using dotted path (e.g., 'a.b.0.c').
    Returns None if any segment is missing.
    """
    cur = data
    if path is None:
        return None
    for raw in str(path).split('.'):
        key = raw.strip()
        if key == "":
            continue
        idx: Optional[int]
        try:
            idx = int(key)
        except ValueError:
            idx = None
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and idx is not None:
            if 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def unflatten(dotted: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a dict with dotted keys into a nested dict.
    Example: {'a.b': 1, 'a.c': 2} -> {'a': {'b': 1, 'c': 2}}
    """
    root: Dict[str, Any] = {}
    for key, value in dotted.items():
        parts = [p for p in str(key).split('.') if p != '']
        cur: Union[Dict[str, Any], List[Any]] = root
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            # We only support dict paths on set; list indices can be added if needed
            if is_last:
                if isinstance(cur, dict):
                    cur[part] = value
                else:
                    # best-effort: cannot set into list cleanly without schema; skip
                    pass
            else:
                if isinstance(cur, dict):
                    if part not in cur or not isinstance(cur[part], dict):
                        cur[part] = {}
                    cur = cur[part]
                else:
                    break
    return root


def fetch_item(base_url: str, token: str, path: str, item_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Fetch a single item by ID for a given resource path.
    Tries a couple of likely URL shapes.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    p = path.strip('/')
    iid = str(item_id).strip('/').split('/')[-1]
    
    logger.info(f"Fetching item {iid} from path {p}")
    
    for root in build_rest_roots(base_url):
        candidates = [
            urljoin(root, f"{p}/{iid}"),
            urljoin(root, f"{p}/{iid}/"),
        ]
        for url in candidates:
            logger.debug(f"Trying URL: {url}")
            data, error = _try_get_json(url, token)
            if data is not None:
                logger.info(f"Successfully fetched item {iid} from {url}")
                # Some endpoints may return an envelope; try to extract first dict
                if isinstance(data, dict) and ('id' in data or 'product_id' in data):
                    return data
                items = extract_items(data)
                if items:
                    logger.info(f"Extracted item from envelope for {iid}")
                    return items[0]
            else:
                logger.debug(f"Failed to fetch from {url}: {error}")
    
    logger.error(f"Failed to fetch item {iid} from all attempted URLs")
    return None


def check_api_permissions(base_url: str, token: str) -> Dict[str, Any]:
    """Sprawdza jakie uprawnienia ma token API"""
    import logging
    logger = logging.getLogger(__name__)
    
    # Sprawdźmy endpoint application-config który pokazuje uprawnienia
    for root in build_rest_roots(base_url):
        candidates = [
            urljoin(root, "application-config"),
            urljoin(root, "application-config/"),
        ]
        for url in candidates:
            logger.info(f"Checking API permissions at {url}")
            data, error = _try_get_json(url, token)
            if data:
                logger.info(f"API permissions response: {data}")
                return data
            else:
                logger.debug(f"Failed to get permissions from {url}: {error}")
    
    return {}


def validate_product_payload(base_url: str, token: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Waliduje payload przed wysłaniem do API. Usuwa nieprawidłowe pola i zwraca oczyszczony payload oraz listę błędów."""
    import logging
    logger = logging.getLogger(__name__)
    
    errors = []
    cleaned_payload = {}
    
    for key, value in payload.items():
        if key == 'attributes':
            # Sprawdź czy atrybuty istnieją
            if isinstance(value, dict):
                cleaned_attributes = {}
                for attr_id, attr_data in value.items():
                    # Sprawdź czy atrybut istnieje przez endpoint attributes
                    attr_url = build_rest_url(base_url, f"attributes/{attr_id}")
                    attr_response, error = _try_get_json(attr_url, token)
                    if attr_response:
                        logger.info(f"Attribute {attr_id} exists, including in payload")
                        cleaned_attributes[attr_id] = attr_data
                    else:
                        logger.warning(f"Attribute {attr_id} does not exist, skipping. Error: {error}")
                        errors.append(f"Atrybut {attr_id} nie istnieje")
                
                if cleaned_attributes:
                    cleaned_payload[key] = cleaned_attributes
            else:
                cleaned_payload[key] = value
        else:
            # Inne pola przepuszczamy bez zmian na tym etapie
            cleaned_payload[key] = value

    # Dodatkowy etap: odfiltruj klucze nieedytowalne wg reguł (na płaskiej strukturze)
    try:
        flat = flatten(cleaned_payload)
        filtered_flat: Dict[str, Any] = {}
        for k, v in flat.items():
            if is_editable_product_field(k):
                filtered_flat[k] = v
            else:
                logger.debug(f"Dropping non-editable key from payload: {k}")
        cleaned_payload = unflatten(filtered_flat)
    except Exception as e:
        logger.warning(f"Failed to post-filter payload by editability rules: {e}")
    
    return cleaned_payload, errors


def update_product(base_url: str, token: str, product_id: Union[str, int], payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Update product with partial payload. Sends only provided fields.
    Tries PATCH/PUT and common payload envelopes. Returns (ok, message).
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Sprawdź uprawnienia API przed próbą aktualizacji
    permissions = check_api_permissions(base_url, token)
    logger.info(f"API permissions check result: {permissions}")
    
    # Waliduj payload przed wysłaniem
    validated_payload, validation_errors = validate_product_payload(base_url, token, payload)
    if validation_errors:
        logger.warning(f"Payload validation found issues: {validation_errors}")
    
    if not validated_payload:
        logger.error("No valid fields to update after validation")
        return False, f"Brak prawidłowych pól do aktualizacji. Błędy: {'; '.join(validation_errors)}"
    
    logger.info(f"Using validated payload: {validated_payload}")
    
    url = build_rest_url(base_url, f"products/{product_id}")
    headers = auth_headers(token)
    headers['Content-Type'] = 'application/json'

    attempts: List[Tuple[str, Dict[str, Any], str]] = []
    # Najlepsze podejście dla API Shopera - PUT z plain payload
    attempts.append(("PUT", validated_payload, "PUT plain"))
    # Fallback - PATCH może działać
    attempts.append(("PATCH", validated_payload, "PATCH plain"))
    # Niektóre API mogą wymagać envelope
    attempts.append(("PUT", {"product": validated_payload}, "PUT product envelope"))

    try:
        last_detail = ""
        last_code = None
        last_response_text = ""
        
        logger.info(f"Attempting to update product {product_id} at {url}")
        logger.info(f"Payload: {validated_payload}")
        
        for method, body, label in attempts:
            logger.info(f"Trying {label} with method {method}")
            logger.info(f"Request body: {body}")
            
            resp = requests.request(method, url, headers=headers, json=body, timeout=20)
            last_code = resp.status_code
            last_response_text = resp.text[:1000]  # Limit for logging
            
            logger.info(f"{label} -> HTTP {resp.status_code}")
            logger.info(f"Response text: {last_response_text}")
            logger.info(f"Response headers: {dict(resp.headers)}")
            
            if resp.status_code in (200, 201, 202, 204):
                logger.info(f"Product {product_id} updated successfully with {label}")
                
                # Dodajmy weryfikację czy dane faktycznie się zmieniły
                logger.info("Verifying changes by fetching updated product...")
                
                # Odczekaj chwilę na aktualizację w bazie
                import time
                time.sleep(1)
                
                updated_product = fetch_item(base_url, token, "products", product_id)
                if updated_product:
                    # Sprawdź czy zmiany zostały zastosowane
                    changes_applied = []
                    changes_failed = []
                    
                    def check_field(flat_key: str, expected_value: Any):
                        actual_value = dot_get(updated_product, flat_key)
                        logger.info(f"Verifying field {flat_key}: expected={expected_value} (type: {type(expected_value)}), actual={actual_value} (type: {type(actual_value)})")
                        
                        # Convert types for comparison - handle different numeric types
                        if isinstance(expected_value, str) and isinstance(actual_value, (int, float)):
                            try:
                                if '.' in expected_value:
                                    expected_value = float(expected_value)
                                else:
                                    expected_value = int(expected_value)
                            except ValueError:
                                pass
                        elif isinstance(expected_value, (int, float)) and isinstance(actual_value, str):
                            try:
                                actual_value = type(expected_value)(actual_value)
                            except ValueError:
                                pass
                        
                        # Handle empty string vs None
                        if expected_value == '' and actual_value is None:
                            changes_applied.append(f"{flat_key}: cleared (None)")
                        elif str(actual_value) == str(expected_value):
                            changes_applied.append(f"{flat_key}: {actual_value}")
                        else:
                            changes_failed.append(f"{flat_key}: expected {expected_value}, got {actual_value}")
                    
                    # Sprawdź zmiany w payload
                    flat_payload = flatten(validated_payload)
                    for flat_key, value in flat_payload.items():
                        check_field(flat_key, value)
                    
                    if changes_applied:
                        logger.info(f"Changes successfully applied: {'; '.join(changes_applied)}")
                    if changes_failed:
                        logger.warning(f"Changes NOT applied: {'; '.join(changes_failed)}")
                        
                        # Sprawdź czy to problem z uprawnieniami
                        error_msg = f"API zwrócił sukces, ale zmiany nie zostały zastosowane: {'; '.join(changes_failed[:3])}"
                        if any('price' in field for field in changes_failed):
                            error_msg += ". Możliwy problem z uprawnieniami do edycji cen lub konfiguracja sklepu blokuje zmiany cen przez API."
                        
                        return True, error_msg
                
                success_msg = "Produkt został zaktualizowany pomyślnie - wszystkie zmiany zastosowane"
                if validation_errors:
                    success_msg += f". Uwagi: {'; '.join(validation_errors)}"
                return True, success_msg
            
            # Parse error details
            try:
                data = resp.json()
                if isinstance(data, dict):
                    error_msg = data.get('error', data.get('message', data.get('errors', str(data))))
                    if isinstance(error_msg, dict):
                        # Handle structured errors like {"field": ["error message"]}
                        error_parts = []
                        for field, messages in error_msg.items():
                            if isinstance(messages, list):
                                error_parts.append(f"{field}: {', '.join(str(m) for m in messages)}")
                            else:
                                error_parts.append(f"{field}: {messages}")
                        error_msg = "; ".join(error_parts)
                    detail = str(error_msg)
                else:
                    detail = str(data)
            except Exception as json_error:
                detail = f"Cannot parse JSON response: {resp.text[:200]}"
                logger.warning(f"JSON parse error: {json_error}")
            
            last_detail = f"{label} -> HTTP {resp.status_code}: {detail}"
            logger.warning(f"Attempt failed: {last_detail}")
            
            # For some 4xx errors, don't retry (bad request, unauthorized, etc.)
            if resp.status_code in (400, 401, 403, 404, 422):
                logger.error(f"Fatal error {resp.status_code}, not retrying: {detail}")
                break
                
        # All attempts failed
        logger.error(f"All update attempts failed for product {product_id}")
        return False, last_detail or f"Aktualizacja nie powiodła się (HTTP {last_code})"
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout updating product {product_id}")
        return False, "Przekroczono czas oczekiwania na odpowiedź API"
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error updating product {product_id}")
        return False, "Błąd połączenia z API"
    except Exception as e:
        logger.error(f"Unexpected error updating product {product_id}: {e}")
        return False, f"Nieoczekiwany błąd: {type(e).__name__}: {e}"


# --- Editability rules -----------------------------------------------------

# Pola które nigdy nie są edytowalne (readonly) - na podstawie dokumentacji API
_READONLY_PRODUCTS_EXACT = {
    # ID fields
    'id', 'product_id', 'stock_id', 'translation_id', 'gfx_id',
    
    # Auto-generated dates
    'add_date', 'edit_date', 'created', 'created_at', 'date_add', 'date_added',
    'modified', 'updated_at', 'date_update', 'date_updated', 'date_mod', 'date_modify',
    
    # Calculated/computed fields
    'calculated_availability_id', 'permalink', 'isdefault', 'lang_id',
    
    # System stats
    'popularity', 'views', 'rating', 'votes', 'type', 'group_id',
    'category_tree_id', 'promo_price', 'loyalty_score', 'loyalty_price', 
    'in_loyalty', 'bestseller', 'newproduct', 'extended', 'default',
    'weight_type', 'sold',  # stock.sold może być edytowane przez sold_relative
}

# Prefiksy pól które nie są edytowalne
_READONLY_PRODUCTS_PREFIXES = (
    'main_image',  # main image via separate endpoints
    'children',    # product bundles via separate endpoints
)

# Pola które SĄ edytowalne zgodnie z oficjalną dokumentacją API Shopera
_EDITABLE_PRODUCTS_FIELDS = {
    # Podstawowe pola produktu (z dokumentacji)
    'producer_id', 'category_id', 'unit_id', 'other_price', 'code', 'tax_id',
    'dimension_w', 'dimension_h', 'dimension_l', 'ean', 'pkwiu',
    'is_product_of_day', 'tags', 'tag_id', 'collections', 'vol_weight',
    'gauge_id', 'currency_id', 'categories', 'unit_price_calculation',
    'feeds_exludes', 'related', 'options',
    
    # Stock pola (z dokumentacji - wszystkie wymienione jako edytowalne)
    'stock.price', 'stock.stock', 'stock.stock_relative', 'stock.warn_level',
    'stock.sold_relative', 'stock.weight', 'stock.availability_id',
    'stock.delivery_id', 'stock.gfx_id', 'stock.package', 
    'stock.price_wholesale', 'stock.price_special',  # Te są edytowalne!
    'stock.calculation_unit_id', 'stock.calculation_unit_ratio',
    'stock.historical_lowest_price', 'stock.wholesale_historical_lowest_price',
    'stock.special_historical_lowest_price', 'stock.code', 'stock.ean',
    
    # Stock warehouses (jeśli włączone)
    'stock.warehouses',
    
    # Stock additional codes (wszystkie edytowalne)
    'stock.additional_codes.bloz12', 'stock.additional_codes.bloz7',
    'stock.additional_codes.code39', 'stock.additional_codes.gtu',
    'stock.additional_codes.isbn', 'stock.additional_codes.kgo',
    'stock.additional_codes.producer', 'stock.additional_codes.warehouse',
    
    # Tłumaczenia (wszystkie edytowalne pola)
    'translations.name', 'translations.short_description', 'translations.description',
    'translations.active', 'translations.seo_title', 'translations.seo_description',
    'translations.seo_keywords', 'translations.seo_url', 'translations.order',
    'translations.main_page', 'translations.main_page_order',
    
    # Atrybuty
    'attributes',
    
    # Special offer (deprecated ale dostępne)
    'special_offer.promo_id', 'special_offer.date_from', 'special_offer.date_to',
    'special_offer.discount', 'special_offer.discount_wholesale', 'special_offer.discount_special',
    'special_offer.discount_type', 'special_offer.condition_type', 'special_offer.stocks',
    
    # Safety information (wszystkie edytowalne)
    'safety_information.gpsr_producer_id', 'safety_information.gpsr_importer_id',
    'safety_information.gpsr_responsible_id', 'safety_information.gpsr_certificates',
    
    # Deprecated ale wciąż dostępne
    'additional_bloz12', 'additional_bloz7', 'additional_code39',
    'additional_gtu', 'additional_isbn', 'additional_kgo',
    'additional_producer', 'additional_warehouse',
}

# Prefiksy pól które nie są edytowalne
_READONLY_PRODUCTS_PREFIXES = (
    'images',  # images usually via separate endpoints
    'attachments',
    'variants',  # variant combos often separate
    'links',
    'stats', 
    'reviews',
)

# Pola które SĄ edytowalne zgodnie z API Shopera
_EDITABLE_PRODUCTS_FIELDS = {
    # Podstawowe pola produktu
    'producer_id', 'category_id', 'unit_id', 'other_price', 'code', 'tax_id',
    'dimension_w', 'dimension_h', 'dimension_l', 'ean', 'pkwiu',
    'is_product_of_day', 'tags', 'tag_id', 'collections', 'vol_weight',
    'gauge_id', 'currency_id', 'categories', 'unit_price_calculation',
    'feeds_exludes',
    
    # Stock pola (pod stock.*) - głównie podstawowe ceny i stany
    'stock.price', 'stock.stock', 'stock.stock_relative', 'stock.warn_level',
    'stock.sold_relative', 'stock.weight', 'stock.availability_id',
    'stock.delivery_id', 'stock.gfx_id', 'stock.package', 'stock.price_wholesale',
    'stock.price_special', 'stock.calculation_unit_id', 'stock.calculation_unit_ratio',
    'stock.historical_lowest_price', 'stock.wholesale_historical_lowest_price',
    'stock.special_historical_lowest_price',
    
    # Stock additional codes
    'stock.additional_codes.bloz12', 'stock.additional_codes.bloz7',
    'stock.additional_codes.code39', 'stock.additional_codes.gtu',
    'stock.additional_codes.isbn', 'stock.additional_codes.kgo',
    'stock.additional_codes.producer', 'stock.additional_codes.warehouse',
    
    # Tłumaczenia (pod translations.*)
    'translations.pl_PL.name', 'translations.pl_PL.short_description',
    'translations.pl_PL.description', 'translations.pl_PL.active',
    'translations.pl_PL.seo_title', 'translations.pl_PL.seo_description',
    'translations.pl_PL.seo_keywords', 'translations.pl_PL.seo_url',
    'translations.pl_PL.order', 'translations.pl_PL.main_page',
    'translations.pl_PL.main_page_order',
    
    # Atrybuty (pod attributes.*)
    'attributes',
    
    # Safety information
    'safety_information.gpsr_producer_id', 'safety_information.gpsr_importer_id',
    'safety_information.gpsr_responsible_id', 'safety_information.gpsr_certificates',
    
    # Related products
    'related',
    
    # Deprecated ale wciąż dostępne
    'additional_bloz12', 'additional_bloz7', 'additional_code39',
    'additional_gtu', 'additional_isbn', 'additional_kgo',
    'additional_producer', 'additional_warehouse',
}


def is_readonly_product_key(key: str) -> bool:
    k = str(key).strip('.').lower()
    # Any path segment equal to readonly exact matches
    parts = [p for p in k.split('.') if p]
    if any(p in _READONLY_PRODUCTS_EXACT for p in parts):
        return True
    # Prefix-based blocks
    for pref in _READONLY_PRODUCTS_PREFIXES:
        if k.startswith(pref + '.') or k == pref:
            return True
    # Generic timestamp/date fields
    if k.startswith('date_') or k.startswith('add_date') or k.startswith('edit_date'):
        return True
    return False


def is_editable_product_field(key: str) -> bool:
    """Sprawdza czy pole produktu jest edytowalne na podstawie oficjalnej dokumentacji API Shopera."""
    k = str(key).strip('.').lower()
    
    # Najpierw sprawdź czy pole jest na liście readonly
    if is_readonly_product_key(key):
        return False
    
    # Sprawdź czy pole jest wprost na liście edytowalnych
    if k in _EDITABLE_PRODUCTS_FIELDS:
        return True
        
    # Sprawdź wzorce dla dynamicznych pól
    
    # Tłumaczenia - wszystkie lokalizacje (nie tylko pl_PL)
    if k.startswith('translations.') and any(
        k.endswith('.' + field) for field in [
            'name', 'short_description', 'description', 'active',
            'seo_title', 'seo_description', 'seo_keywords', 'seo_url',
            'order', 'main_page', 'main_page_order'
        ]
    ):
        return True
    
    # Stock fields - zgodnie z dokumentacją
    if k.startswith('stock.') and any(
        k.endswith('.' + field) for field in [
            'price', 'stock', 'stock_relative', 'warn_level', 'sold_relative',
            'weight', 'availability_id', 'delivery_id', 'gfx_id', 'package',
            'price_wholesale', 'price_special', 'calculation_unit_id', 
            'calculation_unit_ratio', 'historical_lowest_price',
            'wholesale_historical_lowest_price', 'special_historical_lowest_price',
            'code', 'ean'
        ]
    ):
        return True
    
    # Stock additional codes
    if k.startswith('stock.additional_codes.'):
        return True
    
    # Stock warehouses
    if k.startswith('stock.warehouses.'):
        return True
    
    # Atrybuty - wszystkie pod attributes.*
    if k.startswith('attributes.'):
        return True
    
    # Safety information
    if k.startswith('safety_information.'):
        return True
    
    # Special offer 
    if k.startswith('special_offer.'):
        return True
    
    # Jeśli nie ma jasnej reguły - sprawdź czy to nie jest systemowe pole
    system_keywords = ['_id', 'calculated_', 'system_', 'auto_', 'comp_']
    if any(keyword in k for keyword in system_keywords) and k not in _EDITABLE_PRODUCTS_FIELDS:
        return False
    
    # Domyślnie: potencjalnie edytowalne (sprawdzi API)
    return True


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
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.debug(f"Making GET request to {url}")
        resp = requests.get(url, headers=auth_headers(token), timeout=timeout)
        logger.debug(f"GET {url} -> HTTP {resp.status_code}")
        
        if resp.status_code != 200:
            error_msg = f"HTTP {resp.status_code} for {url}"
            logger.warning(error_msg)
            return None, error_msg
            
        try:
            data = resp.json()
            logger.debug(f"Successfully parsed JSON response from {url}")
            return data, None
        except json.JSONDecodeError as e:
            error_msg = f"JSON decode error for {url}: {e}"
            logger.error(error_msg)
            return None, error_msg
            
    except requests.exceptions.Timeout:
        error_msg = f"Timeout for {url}"
        logger.error(error_msg)
        return None, error_msg
    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection error for {url}: {e}"
        logger.error(error_msg)
        return None, error_msg
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e} for {url}"
        logger.error(error_msg)
        return None, error_msg


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
    """Fetch all items from API with pagination support.
    Shoper API returns pagination info in response: {count, pages, page, list: [...]}
    We'll fetch page by page until we get all items or reach a reasonable limit.
    """
    p = path.strip('/')
    all_items: List[Dict[str, Any]] = []
    page = 1
    per_page = 50  # Shoper API default/max per page
    max_pages = 100  # Safety limit to prevent infinite loops
    
    for root in build_rest_roots(base_url):
        while page <= max_pages:
            candidates = [
                urljoin(root, p) + f'?limit={per_page}&page={page}',
                urljoin(root, p + '/') + f'?limit={per_page}&page={page}',
            ]
            
            data = None
            for url in candidates:
                data, _ = _try_get_json(url, token)
                if data is not None:
                    break
            
            if data is None:
                # If first page failed, try other roots
                if page == 1:
                    break
                else:
                    # No more pages available
                    return all_items[:limit] if limit > 0 else all_items
            
            items = extract_items(data)
            if not items or not isinstance(items, list):
                # No more items, we're done
                return all_items[:limit] if limit > 0 else all_items
            
            all_items.extend(items)
            
            # Check if we've reached the limit
            if limit > 0 and len(all_items) >= limit:
                return all_items[:limit]
            
            # Check pagination metadata from Shoper API
            # Response format: {count: total, pages: total_pages, page: current_page, list: [...]}
            if isinstance(data, dict):
                total_pages = data.get('pages')
                current_page = data.get('page')
                if total_pages and current_page and current_page >= total_pages:
                    # We've fetched all pages
                    return all_items[:limit] if limit > 0 else all_items
            
            # If we got fewer items than per_page, probably last page
            if len(items) < per_page:
                return all_items[:limit] if limit > 0 else all_items
            
            page += 1
        
        # If we successfully fetched items, don't try other roots
        if all_items:
            return all_items[:limit] if limit > 0 else all_items
    
    return []


def resolve_path(resource: str, override: Optional[str]) -> Optional[str]:
    if override:
        return override
    return RESOURCE_TO_PATH.get(resource)


def get_recommended_product_fields() -> List[Dict[str, str]]:
    """Zwraca listę zalecanych pól produktu do edycji z opisami w języku polskim"""
    return [
        # Podstawowe dane produktu
        {"key": "product_id", "label": "ID", "editable": False, "category": "Podstawowe"},
        {"key": "code", "label": "Kod produktu", "editable": True, "category": "Podstawowe"},
        {"key": "ean", "label": "Kod kreskowy (EAN)", "editable": True, "category": "Podstawowe"},
        {"key": "translations.pl_PL.name", "label": "Nazwa", "editable": True, "category": "Podstawowe"},
        {"key": "translations.pl_PL.short_description", "label": "Krótki opis", "editable": True, "category": "Podstawowe"},
        {"key": "translations.pl_PL.description", "label": "Pełny opis", "editable": True, "category": "Podstawowe"},
        {"key": "translations.pl_PL.active", "label": "Aktywny", "editable": True, "category": "Podstawowe"},
        
        # Kategoryzacja
        {"key": "category_id", "label": "Kategoria główna", "editable": True, "category": "Kategoryzacja"},
        {"key": "producer_id", "label": "Producent", "editable": True, "category": "Kategoryzacja"},
        {"key": "categories", "label": "Wszystkie kategorie", "editable": True, "category": "Kategoryzacja"},
        
        # Ceny i promocje
        {"key": "stock.price", "label": "Cena podstawowa", "editable": True, "category": "Ceny"},
        {"key": "stock.price_wholesale", "label": "Cena hurtowa 1", "editable": True, "category": "Ceny"},
        {"key": "stock.price_special", "label": "Cena hurtowa 2", "editable": True, "category": "Ceny"},
        {"key": "other_price", "label": "Cena w innych sklepach", "editable": True, "category": "Ceny"},
        
        # Magazyn
        {"key": "stock.stock", "label": "Stan magazynowy", "editable": True, "category": "Magazyn"},
        {"key": "stock.warn_level", "label": "Poziom alarmu", "editable": True, "category": "Magazyn"},
        {"key": "stock.availability_id", "label": "Dostępność", "editable": True, "category": "Magazyn"},
        {"key": "stock.delivery_id", "label": "Czas wysyłki", "editable": True, "category": "Magazyn"},
        
        # Właściwości fizyczne
        {"key": "stock.weight", "label": "Waga", "editable": True, "category": "Właściwości"},
        {"key": "dimension_w", "label": "Szerokość opakowania", "editable": True, "category": "Właściwości"},
        {"key": "dimension_h", "label": "Wysokość opakowania", "editable": True, "category": "Właściwości"},
        {"key": "dimension_l", "label": "Długość opakowania", "editable": True, "category": "Właściwości"},
        {"key": "unit_id", "label": "Jednostka miary", "editable": True, "category": "Właściwości"},
        
        # SEO
        {"key": "translations.pl_PL.seo_title", "label": "Tytuł SEO", "editable": True, "category": "SEO"},
        {"key": "translations.pl_PL.seo_description", "label": "Opis SEO", "editable": True, "category": "SEO"},
        {"key": "translations.pl_PL.seo_keywords", "label": "Słowa kluczowe SEO", "editable": True, "category": "SEO"},
        {"key": "translations.pl_PL.seo_url", "label": "URL SEO", "editable": True, "category": "SEO"},
        
        # Dodatkowe
        {"key": "translations.pl_PL.order", "label": "Priorytet sortowania", "editable": True, "category": "Dodatkowe"},
        {"key": "pkwiu", "label": "PKWiU", "editable": True, "category": "Dodatkowe"},
        {"key": "tax_id", "label": "Stawka VAT", "editable": True, "category": "Dodatkowe"},
        {"key": "is_product_of_day", "label": "Produkt dnia", "editable": True, "category": "Dodatkowe"},
        {"key": "bestseller", "label": "Bestseller", "editable": False, "category": "Dodatkowe"},
        {"key": "newproduct", "label": "Nowość", "editable": False, "category": "Dodatkowe"},
        
        # Daty (readonly)
        {"key": "add_date", "label": "Data dodania", "editable": False, "category": "System"},
        {"key": "edit_date", "label": "Data modyfikacji", "editable": False, "category": "System"},
    ]
