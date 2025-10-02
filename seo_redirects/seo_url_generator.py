"""
Generator przyjaznych SEO URL dla produktów Shoper.
Tworzy strukturę: kategoria/podkategoria/.../nazwa-produktu-wariant
"""

from typing import List, Optional, Dict, Any
import re
import logging
from modules.shoper import build_rest_roots, _try_get_json, fetch_item, fetch_rows
from .helpers import _ensure_path
from .category_hierarchy import get_category_path as get_hierarchy_path


def slugify(text: str) -> str:
    """Konwertuje tekst na slug przyjazny dla URL"""
    if not text:
        return ''
    
    # Polskie znaki -> ASCII
    polish_map = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z'
    }
    
    for pl, ascii_char in polish_map.items():
        text = text.replace(pl, ascii_char)
    
    # Zamień wszystko co nie jest literą, cyfrą lub spacją na spację
    text = re.sub(r'[^\w\s-]', ' ', text)
    
    # Zamień spacje i podkreślenia na myślniki
    text = re.sub(r'[\s_]+', '-', text)
    
    # Usuń wielokrotne myślniki
    text = re.sub(r'-+', '-', text)
    
    # Zamień na małe litery i usuń myślniki z początku i końca
    text = text.lower().strip('-')
    
    return text


def get_category_path(shop, category_id: int) -> List[Dict[str, Any]]:
    """
    Pobiera PEŁNĄ ścieżkę kategorii od głównej do podrzędnej.
    ZAWSZE zwraca całą hierarchię: Główna → Podkategoria → Pod-podkategoria → ...
    
    Przykład: Dla "Niej" -> "Sukienki" -> "Sukienki letnie"
    Zwraca: [
        {'id': 1, 'name': 'Dla niej', 'slug': 'dla-niej'},
        {'id': 5, 'name': 'Sukienki', 'slug': 'sukienki'},
        {'id': 12, 'name': 'Sukienki letnie', 'slug': 'sukienki-letnie'}
    ]
    """
    import logging
    logger = logging.getLogger(__name__)
    
    categories_path = []
    current_id = category_id
    max_depth = 20  # Zwiększony limit dla głębokiej hierarchii
    depth = 0
    visited_ids = set()  # Zapobieganie pętlom
    
    logger.debug(f"Rozpoczynam pobieranie ścieżki kategorii dla ID: {category_id}")
    
    # Najpierw zbierz wszystkie kategorie w hierarchii (od docelowej do głównej)
    while current_id and depth < max_depth:
        # Zapobiegaj pętlom
        if current_id in visited_ids:
            logger.warning(f"Wykryto pętlę w hierarchii kategorii: {current_id}")
            break
        visited_ids.add(current_id)
        
        category_data = fetch_item(shop.base_url, shop.bearer_token, 'categories', current_id)
        
        if not category_data:
            logger.warning(f"Nie znaleziono kategorii o ID: {current_id}")
            break
        
        # Pobierz nazwę kategorii
        name = None
        slug = None
        
        # Sprawdź różne możliwe struktury odpowiedzi API
        if 'translations' in category_data:
            translations = category_data['translations']
            # Próbuj różne kody języków
            for lang_code in ['pl_PL', 'pl', 'pl-PL']:
                if lang_code in translations:
                    lang_data = translations[lang_code]
                    if 'name' in lang_data:
                        name = lang_data['name']
                    if 'seo_url' in lang_data:
                        slug = lang_data['seo_url']
                    elif 'url' in lang_data:
                        slug = lang_data['url']
                    if name:
                        break
        
        # Fallback - nazwa bezpośrednio w danych
        if not name:
            name = category_data.get('name') or category_data.get('title')
        
        if not slug:
            slug = category_data.get('seo_url') or category_data.get('url')
        
        # Jeśli slug zawiera pełną ścieżkę (np. /dla-niej/sukienki), użyj tylko ostatniego segmentu
        if slug and '/' in slug:
            slug_parts = [p for p in slug.split('/') if p]
            if slug_parts:
                slug = slug_parts[-1]  # Weź ostatni segment
        
        # Jeśli nie ma slug, wygeneruj z nazwy
        if not slug and name:
            slug = slugify(name)
        
        if name or slug:
            # Wstaw na początku (odwracamy kolejność)
            categories_path.insert(0, {
                'id': current_id,
                'name': name or slug,
                'slug': slug or slugify(name or ''),
                'level': depth  # Dodaj poziom dla debugowania
            })
            logger.debug(f"Dodano kategorię: {name} (ID: {current_id}, slug: {slug}, poziom: {depth})")
        
        # Sprawdź czy jest kategoria nadrzędna
        parent_id = category_data.get('parent_id')
        if parent_id is None:
            # Czasami parent_id może być w innym miejscu
            parent_id = category_data.get('category_id')
        
        logger.debug(f"Kategoria {current_id} ma parent_id: {parent_id}")
        
        # Jeśli parent_id == 0, None, lub równe current_id, to jesteśmy w głównej kategorii
        if not parent_id or parent_id == 0 or parent_id == current_id:
            logger.debug(f"Osiągnięto kategorię główną: {name}")
            break
        
        # Przejdź do kategorii nadrzędnej
        current_id = parent_id
        depth += 1
    
    logger.info(f"Znaleziono {len(categories_path)} poziomów kategorii dla ID {category_id}")
    for cat in categories_path:
        logger.debug(f"  → {cat['name']} ({cat['slug']})")
    
    return categories_path


def extract_variant_info(product_name: str) -> Optional[str]:
    """
    Wyodrębnia informację o wariancie z nazwy produktu.
    Szuka wzorców typu: "10 szt", "10 sztuk", "20szt.", "100 ml", "2kg" itp.
    """
    # Wzorce dla różnych typów wariantów (kolejność ma znaczenie - od najdłuższych)
    patterns = [
        # wymiary (najpierw, bo są najbardziej złożone)
        r'(\d+(?:\.\d+)?\s*(?:x|×)\s*\d+(?:\.\d+)?(?:\s*(?:mm|cm|m))?)',
        # sztuki (przed jednostkami, które mogą być częścią słowa "sztuk")
        r'(\d+(?:\.\d+)?\s*(?:sztuk|sztuki|szt)\.?)',
        # objętość (z kropką dziesiętną)
        r'(\d+(?:\.\d+)?\s*(?:litr[oóyów]*|l)\.?)',
        r'(\d+(?:\.\d+)?\s*(?:ml)\.?)',
        # waga
        r'(\d+(?:\.\d+)?\s*(?:kilogram[oyów]*|kg)\.?)',
        r'(\d+(?:\.\d+)?\s*(?:gram[oyów]*|g)\.?)',
        # długość
        r'(\d+(?:\.\d+)?\s*(?:metr[oyów]*|mm|cm|m)\.?)',
        # opakowania
        r'(\d+(?:\.\d+)?\s*(?:pack|opak|op|paczk[aie])\.?)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, product_name, re.IGNORECASE)
        if match:
            variant = match.group(1)
            # Znormalizuj:
            # 1. Usuń kropkę na końcu jeśli jest
            variant = variant.rstrip('.')
            # 2. Zamień wielokrotne spacje na pojedynczą
            variant = re.sub(r'\s+', ' ', variant.strip())
            # 3. Zmień spacje na myślniki
            variant = variant.replace(' ', '-')
            return variant.lower()
    
    return None


def get_best_category_for_product(shop, categories_list, all_categories_cache=None):
    """
    Wybiera najlepszą kategorię dla produktu z listy kategorii.
    Preferuje kategorie najbardziej szczegółowe (np. "Sukienki letnie" > "Sukienki codzienne")
    
    Strategia wyboru:
    1. Kategorie ze słowami kluczowymi szczegółowymi (letnie, zimowe, wieczorowe)
    2. Kategorie z dłuższymi nazwami
    3. Kategorie z większym ID (nowsze)
    
    Args:
        shop: Obiekt Shop
        categories_list: Lista ID kategorii lub lista dict z category_id
        all_categories_cache: Cache wszystkich kategorii (opcjonalnie)
        
    Returns:
        dict: Dane wybranej kategorii lub None
    """
    logger = logging.getLogger(__name__)
    
    if not categories_list:
        return None
    
    # Słowa kluczowe wskazujące na bardziej szczegółowe kategorie
    specific_keywords = [
        'letni', 'zimow', 'jesien', 'wiosenn',  # Sezonowe
        'wieczor', 'koktajl', 'casual', 'elegant',  # Style
        'długi', 'krótki', 'midi', 'maxi',  # Długości
        'biznes', 'sport', 'domow'  # Przeznaczenie
    ]
    
    # Pobierz szczegóły wszystkich kategorii (użyj cache jeśli dostępny)
    categories_data = []
    if all_categories_cache is None:
        all_cats = fetch_rows(shop.base_url, shop.bearer_token, 'categories', limit=0)
    else:
        all_cats = all_categories_cache
    
    for cat_item in categories_list:
        # Obsłuż różne formaty: int, str, dict
        if isinstance(cat_item, dict):
            cat_id = cat_item.get('category_id') or cat_item.get('id')
        else:
            cat_id = cat_item
        
        if cat_id:
            # Pobierz z list categories (już pobranej)
            cat_data = next((c for c in all_cats if str(c.get('category_id')) == str(cat_id)), None)
            
            if cat_data:
                name = cat_data.get('translations', {}).get('pl_PL', {}).get('name', '')
                name_lower = name.lower()
                
                # Sprawdź czy nazwa zawiera słowa kluczowe szczegółowe
                has_specific_keyword = any(kw in name_lower for kw in specific_keywords)
                
                categories_data.append({
                    'id': cat_id,
                    'name': name,
                    'data': cat_data,
                    'name_length': len(name),
                    'has_keyword': has_specific_keyword
                })
                logger.debug(f"Znaleziono kategorię {cat_id}: {name} (keyword: {has_specific_keyword})")
    
    if not categories_data:
        return None
    
    # Sortuj: najpierw te ze słowami kluczowymi, potem po długości nazwy, na końcu po ID
    categories_data.sort(key=lambda x: (
        not x['has_keyword'],  # False (ma keyword) < True (nie ma) 
        -x['name_length'],  # Dłuższe nazwy najpierw
        -(int(x['id']) if isinstance(x['id'], str) else x['id'])  # Większe ID najpierw
    ))
    
    best = categories_data[0]
    logger.info(f"Wybrano kategorię: {best['name']} (ID: {best['id']})")
    
    return best['data']


def generate_seo_url_for_product(
    shop, 
    product_id: int, 
    selected_category_id: Optional[int] = None,
    use_full_hierarchy: bool = True,
    all_categories_cache: Optional[list] = None
) -> Optional[str]:
    """
    Generuje przyjazny SEO URL dla produktu na podstawie:
    - Pełnej hierarchii kategorii (np. dla-niej/sukienki/sukienki-letnie)
    - Nazwy produktu (przekonwertowanej na slug)
    - Wariantu sztukowego jeśli występuje (np. 10-sztuk)
    
    Args:
        shop: Obiekt Shop
        product_id: ID produktu
        selected_category_id: Jeśli podano, używa tej kategorii (bez pytania)
        use_full_hierarchy: Czy używać pełnej hierarchii (True) czy tylko jednej kategorii (False)
        all_categories_cache: Cache wszystkich kategorii (opcjonalnie, dla wydajności)
    
    Przykład: /dla-niej/sukienki/sukienki-letnie/sukienka-olowkowa-sunnyday-pupa
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Pobierz dane produktu
    product_data = fetch_item(shop.base_url, shop.bearer_token, 'products', product_id)
    
    if not product_data:
        logger.error(f"Nie udało się pobrać danych produktu {product_id}")
        return None
    
    # Pobierz nazwę produktu
    product_name = None
    
    if 'translations' in product_data:
        translations = product_data['translations']
        for lang_code in ['pl_PL', 'pl', 'pl-PL']:
            if lang_code in translations:
                lang_data = translations[lang_code]
                if 'name' in lang_data:
                    product_name = lang_data['name']
                    break
    
    if not product_name:
        product_name = product_data.get('name') or product_data.get('title')
    
    if not product_name:
        logger.error(f"Produkt {product_id} nie ma nazwy")
        return None
    
    logger.info(f"Produkt: {product_name} (ID: {product_id})")
    
    # Sprawdź pole 'categories' - API Shoper zwraca listę ID kategorii
    categories = product_data.get('categories', [])
    logger.debug(f"Pole 'categories': {categories}")
    
    # Dodaj category_id i main_category_id do listy jeśli istnieją
    if product_data.get('category_id'):
        if product_data['category_id'] not in categories:
            categories.insert(0, product_data['category_id'])
    if product_data.get('main_category_id'):
        if product_data['main_category_id'] not in categories:
            categories.insert(0, product_data['main_category_id'])
    
    # Obsługa wyboru kategorii
    selected_category = None
    category_id_to_use = selected_category_id
    
    if not category_id_to_use and categories:
        unique_categories = list(set(str(c) for c in categories))
        logger.info(f"Produkt ma {len(unique_categories)} unikalnych kategorii: {unique_categories}")
        
        if len(unique_categories) == 1:
            # Tylko jedna kategoria - użyj jej
            category_id_to_use = unique_categories[0]
            logger.info(f"Automatycznie wybrano jedyną kategorię: {category_id_to_use}")
        else:
            # Wiele kategorii - użyj najlepszej (z preferencją słów kluczowych)
            selected_category = get_best_category_for_product(shop, categories, all_categories_cache)
            if selected_category:
                category_id_to_use = selected_category.get('category_id')
                logger.info(f"Auto-wybrano najlepszą kategorię: {category_id_to_use}")
    
    # Pobierz szczegóły wybranej kategorii
    category_path_slugs = []
    if category_id_to_use:
        # Pobierz dane kategorii z API (użyj cache jeśli dostępny)
        if all_categories_cache is None:
            all_cats = fetch_rows(shop.base_url, shop.bearer_token, 'categories', limit=0)
        else:
            all_cats = all_categories_cache
        cat_data = next((c for c in all_cats if str(c.get('category_id')) == str(category_id_to_use)), None)
        
        if cat_data:
            cat_name = cat_data.get('translations', {}).get('pl_PL', {}).get('name', '')
            logger.info(f"Kategoria: {cat_name} (ID: {category_id_to_use})")
            
            if use_full_hierarchy:
                # Użyj pełnej hierarchii (z bazy danych lub mappingu)
                category_path_slugs = get_hierarchy_path(int(category_id_to_use), cat_name, shop)
                logger.info(f"Pełna ścieżka kategorii: {' / '.join(category_path_slugs)}")
            else:
                # Tylko slug kategorii (bez hierarchii)
                category_path_slugs = [slugify(cat_name)]
                logger.info(f"Slug kategorii (bez hierarchii): {category_path_slugs[0]}")
        else:
            logger.warning(f"Nie znaleziono kategorii {category_id_to_use} w API")
    else:
        logger.warning(f"Produkt {product_id} nie ma przypisanych kategorii")
    
    # Buduj URL
    url_parts = []
    
    # Dodaj pełną ścieżkę kategorii (hierarchia)
    if category_path_slugs:
        url_parts.extend(category_path_slugs)
    
    # Sprawdź czy produkt ma wariant sztukowy
    variant_info = extract_variant_info(product_name)
    
    # Usuń informację o wariancie z nazwy produktu do slugu (dodamy ją na końcu)
    product_name_for_slug = product_name
    if variant_info:
        # Usuń wariant z nazwy, żeby nie duplikować
        product_name_for_slug = re.sub(
            r'\d+\s*(?:szt|sztuk|sztuki|ml|l|litr|g|kg|gram|mm|cm|m|pack|opak|paczka)\.?\s*',
            '',
            product_name,
            flags=re.IGNORECASE
        ).strip()
    
    # Dodaj slug nazwy produktu
    product_slug = slugify(product_name_for_slug)
    if product_slug:
        url_parts.append(product_slug)
    
    # Dodaj wariant na końcu jeśli istnieje
    if variant_info:
        url_parts.append(variant_info)
    
    if not url_parts:
        logger.error("Nie udało się wygenerować żadnych części URL")
        return None
    
    # Złóż URL
    seo_url = '/' + '/'.join(url_parts)
    
    logger.info(f"Wygenerowany URL: {seo_url}")
    
    return _ensure_path(seo_url)


def get_product_shoper_url(shop, product_id: int) -> Optional[str]:
    """
    Pobiera oryginalny URL produktu z Shopera (ten mniej ładny, systemowy).
    To będzie target_url w przekierowaniu.
    """
    product_data = fetch_item(shop.base_url, shop.bearer_token, 'products', product_id)
    
    if not product_data:
        return None
    
    # Szukaj URL w różnych miejscach
    url = None
    
    # Sprawdź translations
    if 'translations' in product_data:
        translations = product_data['translations']
        for lang_code in ['pl_PL', 'pl', 'pl-PL']:
            if lang_code in translations:
                lang_data = translations[lang_code]
                url = lang_data.get('seo_url') or lang_data.get('url')
                if url:
                    break
    
    # Fallback
    if not url:
        url = product_data.get('seo_url') or product_data.get('url')
    
    # Jeśli nadal nie ma URL, użyj standardowego formatu Shopera
    if not url:
        # Typowy format URL w Shoperze to coś w stylu /prod{ID} lub /p{ID}
        url = f"/prod{product_id}"
    
    return _ensure_path(url) if url else None


def generate_redirects_for_products(shop, product_ids: List[int]) -> List[Dict[str, Any]]:
    """
    Generuje przekierowania SEO dla listy produktów.
    Zwraca listę dict z danymi do utworzenia RedirectRule:
    {
        'product_id': int,
        'product_name': str,
        'source_url': str (przyjazny SEO URL),
        'target_url': str (oryginalny URL Shopera),
        'status': 'success' | 'error',
        'message': str
    }
    """
    results = []
    
    for product_id in product_ids:
        try:
            # Generuj przyjazny URL
            seo_url = generate_seo_url_for_product(shop, product_id)
            
            if not seo_url:
                results.append({
                    'product_id': product_id,
                    'product_name': f'Produkt #{product_id}',
                    'source_url': None,
                    'target_url': None,
                    'status': 'error',
                    'message': 'Nie udało się wygenerować SEO URL'
                })
                continue
            
            # Pobierz oryginalny URL Shopera
            shoper_url = get_product_shoper_url(shop, product_id)
            
            if not shoper_url:
                results.append({
                    'product_id': product_id,
                    'product_name': f'Produkt #{product_id}',
                    'source_url': seo_url,
                    'target_url': None,
                    'status': 'error',
                    'message': 'Nie udało się pobrać URL docelowego z Shopera'
                })
                continue
            
            # Pobierz nazwę produktu dla lepszego komunikatu
            product_data = fetch_item(shop.base_url, shop.bearer_token, 'products', product_id)
            product_name = f'Produkt #{product_id}'
            
            if product_data:
                if 'translations' in product_data:
                    translations = product_data['translations']
                    for lang_code in ['pl_PL', 'pl', 'pl-PL']:
                        if lang_code in translations:
                            lang_data = translations[lang_code]
                            if 'name' in lang_data:
                                product_name = lang_data['name']
                                break
                
                if product_name == f'Produkt #{product_id}':
                    product_name = product_data.get('name') or product_name
            
            results.append({
                'product_id': product_id,
                'product_name': product_name,
                'source_url': seo_url,
                'target_url': shoper_url,
                'status': 'success',
                'message': 'OK'
            })
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Błąd generowania przekierowania dla produktu {product_id}: {e}")
            
            results.append({
                'product_id': product_id,
                'product_name': f'Produkt #{product_id}',
                'source_url': None,
                'target_url': None,
                'status': 'error',
                'message': f'Błąd: {str(e)}'
            })
    
    return results
