"""
Pomocnicze funkcje do wyboru kategorii dla produktów.
"""

import logging
from modules.shoper import fetch_rows

logger = logging.getLogger(__name__)


def get_product_categories_for_selection(shop, product_id, product_data=None, all_categories_cache=None):
    """
    Pobiera listę kategorii produktu z pełnymi informacjami do wyboru.
    
    Args:
        shop: Obiekt Shop
        product_id: ID produktu
        product_data: Opcjonalnie dane produktu (aby nie pobierać ponownie)
        all_categories_cache: Cache wszystkich kategorii (aby nie pobierać wielokrotnie)
        
    Returns:
        list: Lista dict z informacjami o kategoriach:
              [{'id': 24, 'name': 'Sukienki letnie', 'path': ['dla-niej', 'sukienki', 'sukienki-letnie']}, ...]
    """
    from modules.shoper import fetch_item
    from .category_hierarchy import get_category_path
    
    if not product_data:
        product_data = fetch_item(shop.base_url, shop.bearer_token, 'products', product_id)
        if not product_data:
            return []
    
    # Pobierz listę kategorii produktu
    categories = product_data.get('categories', [])
    if product_data.get('category_id'):
        if product_data['category_id'] not in categories:
            categories.insert(0, product_data['category_id'])
    
    if not categories:
        logger.debug(f"Produkt {product_id} nie ma przypisanych kategorii")
        return []
    
    # Usuń duplikaty
    unique_categories = list(set(str(c) for c in categories))
    
    # Pobierz szczegóły każdej kategorii (użyj cache jeśli dostępny)
    if all_categories_cache is None:
        all_cats = fetch_rows(shop.base_url, shop.bearer_token, 'categories', limit=0)
    else:
        all_cats = all_categories_cache
    
    result = []
    for cat_id in unique_categories:
        cat_data = next((c for c in all_cats if str(c.get('category_id')) == str(cat_id)), None)
        if cat_data:
            cat_name = cat_data.get('translations', {}).get('pl_PL', {}).get('name', '')
            if not cat_name:
                logger.warning(f"Kategoria {cat_id} nie ma nazwy")
                continue
                
            cat_path = get_category_path(int(cat_id), cat_name, shop)
            
            result.append({
                'id': int(cat_id),
                'name': cat_name,
                'path': cat_path,
                'path_display': ' → '.join(cat_path) if cat_path else cat_name,
                'full_url_path': '/' + '/'.join(cat_path) if cat_path else ''
            })
    
    return result


def generate_urls_for_all_categories(shop, product_id, product_name):
    """
    Generuje URL SEO dla produktu dla KAŻDEJ kategorii do której należy.
    
    Args:
        shop: Obiekt Shop
        product_id: ID produktu
        product_name: Nazwa produktu
        
    Returns:
        list: Lista dict z wygenerowanymi URL dla każdej kategorii:
              [{'category_id': 24, 'category_name': '...', 'seo_url': '/dla-niej/sukienki/sukienki-letnie/produkt'}, ...]
    """
    from .seo_url_generator import generate_seo_url_for_product
    from modules.shoper import fetch_item
    
    # Pobierz dane produktu
    product_data = fetch_item(shop.base_url, shop.bearer_token, 'products', product_id)
    if not product_data:
        return []
    
    # Pobierz kategorie produktu
    categories_info = get_product_categories_for_selection(shop, product_id, product_data)
    
    results = []
    for cat_info in categories_info:
        # Wygeneruj URL dla tej konkretnej kategorii
        seo_url = generate_seo_url_for_product(
            shop, 
            product_id, 
            selected_category_id=cat_info['id'],
            use_full_hierarchy=True
        )
        
        if seo_url:
            results.append({
                'category_id': cat_info['id'],
                'category_name': cat_info['name'],
                'category_path': cat_info['path_display'],
                'seo_url': seo_url
            })
    
    return results
