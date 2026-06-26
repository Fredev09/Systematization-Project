"""
Template tags para acceder a valores de formularios dinámicos desde
templates legacy que antes usaban modelos fijos.

Uso:

    {% load dynamic_values %}

    {# Obtener el valor de un campo #}
    {% campo_valor registro "nombre" %}

    {# Obtener el valor con prefijo ID (útil para relaciones) #}
    {% relacion_display registro "producto" %}

    {# Iterar sobre todos los campos y valores de un registro #}
    {% for nombre, valor in registro_valores registro %}
        {{ nombre }}: {{ valor }}
    {% endfor %}
"""

from django import template

from ..models import ValorCampo

register = template.Library()


@register.simple_tag
def campo_valor(registro, nombre_campo, default=''):
    """
    Extrae el valor de un campo de un registro dinámico.

    Ejemplo en template:
        {% campo_valor producto "nombre" %}
        {% campo_valor producto "precio"|formato_pesos %}
    """
    try:
        vc = ValorCampo.objects.get(registro=registro, campo__nombre=nombre_campo)
        return vc.valor
    except ValorCampo.DoesNotExist:
        return default


@register.simple_tag
def campo_valor_id(registro_id, nombre_campo, default=''):
    """
    Extrae el valor de un campo usando el ID del registro directamente.

    Útil cuando solo tienes el ID (ej: en relaciones).
    """
    try:
        vc = ValorCampo.objects.get(registro_id=registro_id, campo__nombre=nombre_campo)
        return vc.valor
    except ValorCampo.DoesNotExist:
        return default


@register.simple_tag
def relacion_display(registro, nombre_campo, default=''):
    """
    Resuelve el display de un campo tipo 'relacion'.

    Si el campo 'producto' contiene "5", esta tag buscará el registro #5
    en el formulario destino y devolverá su primer campo de texto.

    Ejemplo:
        {% relacion_display venta "producto" %}
        → "Camisa Azul"
    """
    try:
        vc = ValorCampo.objects.get(registro=registro, campo__nombre=nombre_campo)
        ref_id = vc.valor.strip()
        if not ref_id.isdigit():
            return ref_id

        campo = vc.campo
        if campo.tipo != 'relacion' or not campo.formulario_destino_id:
            return ref_id

        from ..models import Registro, Campo as CampoModel
        ref_registro = Registro.objects.filter(
            id=int(ref_id),
            formulario_id=campo.formulario_destino_id
        ).first()
        if not ref_registro:
            return default or f'#{ref_id}'

        primer_campo = CampoModel.objects.filter(
            formulario_id=campo.formulario_destino_id,
            activo=True
        ).order_by('orden').first()

        if not primer_campo:
            return f'#{ref_id}'

        display_vc = ValorCampo.objects.filter(
            registro=ref_registro,
            campo=primer_campo
        ).first()

        if display_vc:
            return display_vc.valor
        return f'#{ref_id}'
    except ValorCampo.DoesNotExist:
        return default


@register.simple_tag
def resolver_url_imagen(registro, nombre_campo):
    """
    Retorna la URL de una imagen almacenada en un campo tipo 'imagen'.
    
    Si el valor almacenado comienza con 'http', se devuelve tal cual.
    Si no, se asume que es una ruta relativa a MEDIA_URL.
    """
    from django.conf import settings
    valor = campo_valor(registro, nombre_campo, '')
    if not valor:
        return ''
    if valor.startswith('http://') or valor.startswith('https://'):
        return valor
    return f'{settings.MEDIA_URL}{valor}'


@register.filter
def valor_por_campo(registro, nombre_campo):
    """Filter version: {{ registro|valor_por_campo:\"nombre\" }}"""
    return campo_valor(registro, nombre_campo)


@register.filter
def display_relacion(registro, nombre_campo):
    """Filter version: {{ registro|display_relacion:\"producto\" }}"""
    return relacion_display(registro, nombre_campo)


@register.simple_tag
def get_campos_formulario(nombre_formulario):
    """
    Obtiene los campos activos de un formulario dinámico por su nombre.

    Útil cuando un template necesita conocer los campos del formulario
    sin que la vista los pase explícitamente en el contexto.

    Uso:
        {% load dynamic_values %}
        {% get_campos_formulario "Productos" as campos_producto %}

        {% for campo in campos_producto %}
            {{ campo.nombre }}
        {% endfor %}
    """
    from ..services_dynamic import DynamicService
    return DynamicService.obtener_campos_activos(nombre_formulario)
