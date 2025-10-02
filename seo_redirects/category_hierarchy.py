"""
Mapowanie hierarchii kategorii dla SEO URL.
Ponieważ API Shoper nie wspiera parent_id, definiujemy hierarchię ręcznie.
"""

# ============================================================================
# OPCJONALNE MAPOWANIE HIERARCHII
# ============================================================================
# Jeśli chcesz ręcznie zdefiniować hierarchię dla konkretnego sklepu,
# dodaj tutaj mapowanie: category_id -> pełna ścieżka
#
# UWAGA: To jest OPCJONALNE! Jeśli nie dodasz kategorii tutaj,
# system użyje tylko nazwy kategorii (płaska struktura).
#
# Przykład:
# CATEGORY_HIERARCHY = {
#     22: ['dla-niej', 'sukienki', 'sukienki-codzienne'],
#     24: ['dla-niej', 'sukienki', 'sukienki-letnie'],
# }
# ============================================================================

CATEGORY_HIERARCHY = {
    # Zostaw pusty lub dodaj swoje kategorie dla konkretnego sklepu
}

# Nie używane - zostawione dla kompatybilności wstecznej
CATEGORY_NAME_TO_SLUG = {}
AUTO_HIERARCHY_RULES = []


def get_category_path(category_id, category_name=None, shop=None):
    """
    Zwraca pełną ścieżkę kategorii.
    
    Strategia:
    1. Sprawdź w bazie danych (automatycznie zbudowana hierarchia)
    2. Sprawdź w manualnym mapowaniu (jeśli użytkownik zdefiniował)
    3. Fallback - tylko slug kategorii
    
    Args:
        category_id: ID kategorii
        category_name: Nazwa kategorii
        shop: Obiekt Shop (wymagany dla bazy danych)
        
    Returns:
        list: Lista slugów ścieżki, np. ['dla-niej', 'sukienki', 'sukienki-letnie']
    """
    from seo_redirects.seo_url_generator import slugify
    
    # 1. Spróbuj pobrać z bazy danych (automatyczna hierarchia)
    if shop:
        from seo_redirects.hierarchy_builder import get_category_hierarchy_from_db
        db_path = get_category_hierarchy_from_db(shop, category_id)
        if db_path:
            return db_path
    
    # 2. Sprawdź w manualnym mapowaniu (backward compatibility)
    if category_id in CATEGORY_HIERARCHY:
        return CATEGORY_HIERARCHY[category_id].copy()
    
    # 3. Fallback - tylko slug kategorii (płaska struktura)
    if category_name:
        slug = slugify(category_name)
        return [slug]
    
    return []


def update_hierarchy(category_id, path):
    """
    Dodaje lub aktualizuje hierarchię dla kategorii.
    Przydatne do budowania mapowania przez interfejs użytkownika.
    
    Args:
        category_id: ID kategorii
        path: Lista slugów, np. ['dla-niej', 'sukienki', 'sukienki-letnie']
    """
    CATEGORY_HIERARCHY[category_id] = path


def get_all_hierarchies():
    """Zwraca wszystkie zdefiniowane hierarchie"""
    return CATEGORY_HIERARCHY.copy()


def suggest_hierarchy_from_name(category_name):
    """
    Sugeruje hierarchię na podstawie nazwy kategorii.
    
    Returns:
        list: Sugerowana ścieżka
    """
    import re
    from seo_redirects.seo_url_generator import slugify
    
    name_lower = category_name.lower()
    
    # Sprawdź reguły
    for pattern, prefix in AUTO_HIERARCHY_RULES:
        if re.search(pattern, name_lower):
            slug = CATEGORY_NAME_TO_SLUG.get(category_name, slugify(category_name))
            return prefix + [slug]
    
    # Fallback
    return [slugify(category_name)]
