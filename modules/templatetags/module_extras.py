from django import template

register = template.Library()


@register.filter(name="dotget")
def dotget(value, path: str):
    """Resolve nested keys from dict/list using dotted path, e.g. "a.b.0.c".
    Returns empty string if any step is missing.
    """
    data = value
    if path is None:
        return ""
    for raw in str(path).split('.'):
        key = raw.strip()
        if key == "":
            continue
        # List index support
        idx = None
        try:
            idx = int(key)
        except ValueError:
            idx = None

        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list) and idx is not None:
            if 0 <= idx < len(data):
                data = data[idx]
            else:
                return ""
        else:
            return ""

        if data is None:
            return ""

    # Render lists/dicts succinctly
    if isinstance(data, list):
        return ", ".join(map(str, data[:5]))
    if isinstance(data, dict):
        return str(data)
    return data

