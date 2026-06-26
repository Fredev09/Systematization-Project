"""
Validadores para campos de formularios dinámicos.

Centraliza la lógica de validación de valores por tipo de campo
para evitar la dependencia circular entre services_dynamic.py y views.py.
"""

import re
from datetime import datetime

from .models import Campo, Registro


def _validar_valor_campo(campo, valor_raw):
    """Valida un valor según el tipo de campo. Retorna (valor_limpio, error)."""
    if not valor_raw:
        return '', None

    if campo.tipo == 'numero':
        try:
            float(valor_raw.replace(',', '.'))
        except ValueError:
            return None, f'El campo "{campo.nombre}" debe ser un número válido.'
        return valor_raw, None

    if campo.tipo == 'fecha':
        try:
            datetime.strptime(valor_raw, '%Y-%m-%d')
        except ValueError:
            return None, f'El campo "{campo.nombre}" debe ser una fecha válida (YYYY-MM-DD).'
        return valor_raw, None

    if campo.tipo == 'booleano':
        return ('Sí' if valor_raw == 'on' else 'No'), None

    if campo.tipo == 'lista' and campo.opciones:
        if valor_raw not in campo.opciones:
            return None, f'El valor "{valor_raw}" no es una opción válida para "{campo.nombre}".'
        return valor_raw, None

    if campo.tipo == 'email':
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', valor_raw):
            return None, f'El campo "{campo.nombre}" debe ser un correo electrónico válido.'
        return valor_raw, None

    if campo.tipo == 'url':
        if not (valor_raw.startswith('http://') or valor_raw.startswith('https://')):
            return None, f'El campo "{campo.nombre}" debe ser una URL válida (http:// o https://).'
        return valor_raw, None

    if campo.tipo == 'telefono':
        # Acepta dígitos, espacios, +, -, paréntesis
        limpio = re.sub(r'[\s\-\+\(\)]', '', valor_raw)
        if not limpio.isdigit() or len(limpio) < 7:
            return None, f'El campo "{campo.nombre}" debe ser un teléfono válido (mín. 7 dígitos).'
        return valor_raw, None

    if campo.tipo == 'relacion':
        # Validar que el registro referenciado exista
        if valor_raw.isdigit():
            ref_id = int(valor_raw)
            if not Registro.objects.filter(id=ref_id).exists():
                return None, f'El registro #{ref_id} referenciado en "{campo.nombre}" no existe.'
        return valor_raw, None

    if campo.tipo == 'calculado':
        # Solo lectura, no se valida entrada del usuario
        return valor_raw, None

    # texto, textarea, imagen, archivo -> sin validación especial
    return valor_raw, None
