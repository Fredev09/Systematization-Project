from django import template

register = template.Library()


@register.filter
def dict_key(dictionary, key):
    """Obtiene un valor de un diccionario usando una clave variable."""
    if dictionary is None:
        return None
    return dictionary.get(key, '')
