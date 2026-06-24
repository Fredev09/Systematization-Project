from django import template

register = template.Library()


@register.filter
def dict_key(dictionary, key):
    """Obtiene un valor de un diccionario usando una clave variable."""
    if dictionary is None:
        return None
    return dictionary.get(key, '')


@register.filter
def sum_attr(queryset, attr):
    """Suma un atributo numérico a través de todos los objetos de un queryset/lista.
    Uso: {{ formularios|sum_attr:"total_registros" }}
    """
    total = 0
    for obj in queryset:
        try:
            value = getattr(obj, attr, 0)
            if value is None:
                value = 0
            total += int(value)
        except (TypeError, ValueError):
            pass
    return total
