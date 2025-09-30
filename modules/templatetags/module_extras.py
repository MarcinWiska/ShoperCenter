from django import template

register = template.Library()


from django import template

register = template.Library()


@register.filter
def dotget(data, path):
    """Get nested value from dict/list using dotted path (e.g., 'a.b.0.c')"""
    from modules.shoper import dot_get
    return dot_get(data, path)


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary"""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None