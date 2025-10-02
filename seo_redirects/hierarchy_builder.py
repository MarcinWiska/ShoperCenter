"""
Automatyczne budowanie hierarchii kategorii na podstawie danych ze Shoper.
"""
import logging
import re
from typing import Dict, List, Optional
from modules.shoper import fetch_rows
from seo_redirects.seo_url_generator import slugify

logger = logging.getLogger(__name__)


def build_category_hierarchy_from_shoper(shop) -> Dict[int, List[str]]:
    """
    Buduje hierarchię kategorii używając endpoint categories-tree.
    
    Strategia:
    1. Pobierz categories-tree (struktura drzewa z id i children)
    2. Pobierz categories (nazwy i slugi)
    3. Zbuduj hierarchię rekurencyjnie przechodząc drzewo
    
    Args:
        shop: Obiekt Shop
        
    Returns:
        dict: {category_id: [slug1, slug2, slug3]}
        Przykład: {24: ['dla-niej', 'sukienki', 'sukienki-letnie']}
    """
    logger.info(f"Budowanie hierarchii kategorii dla sklepu {shop.name}...")
    
    # 1. Pobierz drzewo kategorii (struktura hierarchii)
    tree = fetch_rows(shop.base_url, shop.bearer_token, 'categories-tree', limit=0)
    logger.info(f"Pobrano drzewo kategorii: {len(tree)} root kategorii")
    
    # 2. Pobierz wszystkie kategorie (nazwy i dane)
    categories = fetch_rows(shop.base_url, shop.bearer_token, 'categories', limit=0)
    logger.info(f"Pobrano {len(categories)} kategorii z API")
    
    # 3. Zbuduj mapę: category_id -> {name, slug}
    category_map = {}
    
    for cat in categories:
        cat_id = int(cat.get('category_id', 0))
        if not cat_id:
            continue
        
        translations = cat.get('translations', {})
        pl_data = translations.get('pl_PL', {})
        name = pl_data.get('name', '')
        
        if not name:
            logger.warning(f"Kategoria {cat_id} nie ma nazwy - pomijam")
            continue
        
        slug = slugify(name)
        
        category_map[cat_id] = {
            'name': name,
            'slug': slug
        }
    
    # 4. Zbuduj hierarchię rekurencyjnie przechodząc drzewo
    hierarchy = {}
    
    def traverse_tree(node: dict, parent_path: List[str] = None):
        """
        Rekurencyjnie przejdź drzewo kategorii i zbuduj hierarchię.
        
        Args:
            node: Węzeł drzewa z polami 'id' i 'children'
            parent_path: Ścieżka rodzica (lista slugów)
        """
        if parent_path is None:
            parent_path = []
        
        cat_id = node.get('id')
        if not cat_id or cat_id not in category_map:
            return
        
        cat_info = category_map[cat_id]
        current_path = parent_path + [cat_info['slug']]
        hierarchy[cat_id] = current_path
        
        logger.debug(f"Kategoria {cat_id} ({cat_info['name']}): {' → '.join(current_path)}")
        
        # Rekurencyjnie przetwórz dzieci
        children = node.get('children', [])
        for child in children:
            traverse_tree(child, current_path)
    
    # Przejdź wszystkie root kategorie
    for root_node in tree:
        traverse_tree(root_node)
    
    logger.info(f"Zbudowano hierarchię dla {len(hierarchy)} kategorii")
    return hierarchy


def extract_hierarchy_from_permalink(permalink: str, category_name: str, category_id: int) -> List[str]:
    """
    Wyciąga hierarchię ze struktury permalink.
    
    Permalink format: https://sklep.pl/pl/c/Dla-niej/Sukienki/Sukienki-letnie/24
    Wynik: ['dla-niej', 'sukienki', 'sukienki-letnie']
    
    Args:
        permalink: URL permalink z API
        category_name: Nazwa kategorii
        category_id: ID kategorii
        
    Returns:
        list: Lista slugów w hierarchii
    """
    if not permalink:
        return []
    
    # Wyciągnij część po /c/
    # Format: .../c/Segment1/Segment2/Segment3/ID
    match = re.search(r'/c/([^?]+)', permalink)
    if not match:
        return []
    
    path = match.group(1)
    
    # Usuń ID kategorii z końca (jeśli jest)
    # Format: Dla-niej/Sukienki/Sukienki-letnie/24
    parts = path.rstrip('/').split('/')
    
    # Ostatnia część to często ID - usuń jeśli jest liczbą
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    
    # Konwertuj każdą część na slug
    slugs = []
    for part in parts:
        if part:
            # Permalink już ma format z myślnikami, tylko zmieniamy na lowercase
            slug = part.lower()
            # Dodatkowo oczyść ze znaków specjalnych
            slug = slugify(slug)
            if slug:
                slugs.append(slug)
    
    return slugs


def save_hierarchy_to_database(shop, hierarchy: Dict[int, List[str]]):
    """
    Zapisuje hierarchię do bazy danych.
    
    Args:
        shop: Obiekt Shop
        hierarchy: dict {category_id: [slug1, slug2, ...]}
    """
    from seo_redirects.models import CategoryHierarchy
    
    logger.info(f"Zapisywanie hierarchii do bazy dla {len(hierarchy)} kategorii...")
    
    created = 0
    updated = 0
    
    # Pobierz wszystkie kategorie ponownie aby mieć nazwy
    categories = fetch_rows(shop.base_url, shop.bearer_token, 'categories', limit=0)
    cat_names = {}
    for cat in categories:
        cat_id = int(cat.get('category_id', 0))
        name = cat.get('translations', {}).get('pl_PL', {}).get('name', '')
        if cat_id and name:
            cat_names[cat_id] = name
    
    for cat_id, path_slugs in hierarchy.items():
        if cat_id not in cat_names:
            continue
        
        name = cat_names[cat_id]
        slug = path_slugs[-1] if path_slugs else slugify(name)
        level = len(path_slugs) - 1
        
        # Utwórz lub zaktualizuj
        obj, created_flag = CategoryHierarchy.objects.update_or_create(
            shop=shop,
            category_id=cat_id,
            defaults={
                'category_name': name,
                'category_slug': slug,
                'path_slugs': path_slugs,
                'level': level,
            }
        )
        
        if created_flag:
            created += 1
        else:
            updated += 1
    
    logger.info(f"✅ Zapisano hierarchię: utworzono {created}, zaktualizowano {updated}")
    return created, updated


def get_category_hierarchy_from_db(shop, category_id: int) -> Optional[List[str]]:
    """
    Pobiera hierarchię kategorii z bazy danych.
    
    Args:
        shop: Obiekt Shop
        category_id: ID kategorii
        
    Returns:
        list: Ścieżka slugów lub None
    """
    from seo_redirects.models import CategoryHierarchy
    
    try:
        hierarchy = CategoryHierarchy.objects.get(shop=shop, category_id=category_id)
        return hierarchy.path_slugs
    except CategoryHierarchy.DoesNotExist:
        return None


def refresh_hierarchy_for_shop(shop):
    """
    Odświeża hierarchię kategorii dla sklepu.
    Pobiera dane z API i zapisuje do bazy.
    
    Args:
        shop: Obiekt Shop
        
    Returns:
        tuple: (created, updated)
    """
    logger.info(f"🔄 Odświeżanie hierarchii kategorii dla {shop.name}...")
    
    # Zbuduj hierarchię z API
    hierarchy = build_category_hierarchy_from_shoper(shop)
    
    # Zapisz do bazy
    created, updated = save_hierarchy_to_database(shop, hierarchy)
    
    logger.info(f"✅ Hierarchia odświeżona: {created} nowych, {updated} zaktualizowanych")
    
    return created, updated
