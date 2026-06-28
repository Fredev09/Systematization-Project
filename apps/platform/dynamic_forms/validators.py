"""
Validadores para campos de formularios dinámicos.
Centraliza la lógica de validación de valores por tipo de campo
para evitar la dependencia circular entre services_dynamic.py y views.py.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .models import Campo, Registro

# ---------------------------------------------------------------------------
# Normalizadores de formato (FASE 5: Importación extremadamente robusta)
# ---------------------------------------------------------------------------

_VALORES_VERDADEROS = {'sí', 'si', 'true', 'yes', 'on', '1', 'x', '✓', '✔', 'check', 'cierto', 'v'}
_VALORES_FALSOS = {'no', 'false', 'off', '0', '', 'nunca', 'falso'}


def normalizar_booleano(valor_raw: str) -> Optional[str]:
    valor_lower = valor_raw.strip().lower()
    if valor_lower in _VALORES_VERDADEROS:
        return 'Sí'
    if valor_lower in _VALORES_FALSOS:
        return 'No'
    return None


def normalizar_fecha(valor_raw: str) -> Optional[str]:
    valor = valor_raw.strip()
    if not valor:
        return None

    # YYYY-MM-DD (ISO)
    try:
        dt = datetime.strptime(valor, '%Y-%m-%d')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        pass

    # DD/MM/YYYY
    try:
        dt = datetime.strptime(valor, '%d/%m/%Y')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        pass

    # MM/DD/YYYY
    try:
        dt = datetime.strptime(valor, '%m/%d/%Y')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        pass

    # DD-MM-YYYY
    try:
        dt = datetime.strptime(valor, '%d-%m-%Y')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        pass

    # MM-DD-YYYY
    try:
        dt = datetime.strptime(valor, '%m-%d-%Y')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        pass

    # YYYY/MM/DD
    try:
        dt = datetime.strptime(valor, '%Y/%m/%d')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        pass

    return None


def normalizar_moneda(valor_raw: str) -> Optional[str]:
    valor = valor_raw.strip()
    if not valor:
        return None

    # Remover prefijos de moneda ($, USD, COP, EUR, etc.)
    valor = re.sub(r'^[\$€£¥]+', '', valor).strip()
    valor = re.sub(r'^(USD|EUR|COP|GBP|MXN|ARS|CLP|PEN|BOB|UYU|PYG|CRC|DOP)\s*', '', valor, flags=re.IGNORECASE).strip()
    valor = re.sub(r'\s+(USD|EUR|COP|GBP|MXN|ARS|CLP|PEN|BOB|UYU|PYG|CRC|DOP)$', '', valor, flags=re.IGNORECASE).strip()

    if not valor:
        return None

    # Manejar formato europeo: 1.000,50 → 1000.50
    if ',' in valor and '.' in valor:
        if valor.rindex(',') > valor.rindex('.'):
            valor = valor.replace('.', '').replace(',', '.')
        else:
            valor = valor.replace(',', '')
    elif ',' in valor:
        valor = valor.replace(',', '.')
    elif '.' in valor and valor.count('.') == 1:
        pass
    elif '.' in valor:
        # Posible separador de miles: 1.000 → 1000
        parts = valor.split('.')
        if all(len(p) == 3 for p in parts[:-1]) and len(parts[-1]) != 3:
            valor = valor.replace('.', '')
        # else mantener como está (decimal con puntos)
    elif re.match(r'^\d+$', valor):
        pass
    else:
        valor = re.sub(r'[^\d.,]', '', valor)

    try:
        num = float(valor) if valor else 0.0
        if num < 0:
            return None
        return f'{num:.2f}'.rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return None


def normalizar_numero(valor_raw: str, permitir_decimales: bool = True) -> Optional[str]:
    valor = valor_raw.strip()
    if not valor:
        return None

    # Detectar formato: si hay coma y punto, decidir cuál es decimal
    if ',' in valor and '.' in valor:
        if valor.rindex(',') > valor.rindex('.'):
            # Europeo: 1.000,50 → 1000.50
            valor = valor.replace('.', '').replace(',', '.')
        else:
            # US: 1,000.50 → 1000.50
            valor = valor.replace(',', '')
    elif ',' in valor:
        valor = valor.replace(',', '.')
    elif valor.count('.') > 1:
        # Miles (1.000.50 → inválido como número)
        # Asumir 1.000 → 1000
        parts = valor.split('.')
        if all(len(p) == 3 for p in parts[:-1]) and len(parts[-1]) != 3:
            valor = valor.replace('.', '')

    if permitir_decimales:
        valor = re.sub(r'[^\d.\-]', '', valor)
    else:
        valor = re.sub(r'[^\d\-]', '', valor)

    try:
        if permitir_decimales:
            num = float(valor)
            if num == int(num):
                return str(int(num))
            return str(num)
        else:
            return str(int(valor))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Fecha serial de Excel
# ---------------------------------------------------------------------------

def _es_fecha_serial(valor: str) -> bool:
    try:
        num = float(valor)
        if 1 <= num <= 2958465:
            return True
    except (ValueError, TypeError):
        pass
    return False


def _serial_a_fecha(serial: float) -> str:
    from datetime import date, timedelta
    if serial < 61:
        delta = timedelta(days=int(serial) - 1)
        fecha_base = date(1899, 12, 30)
    else:
        delta = timedelta(days=int(serial) - 1)
        fecha_base = date(1899, 12, 30)
    return (fecha_base + delta).strftime('%Y-%m-%d')


# ---------------------------------------------------------------------------
# Validación principal
# ---------------------------------------------------------------------------


def _validar_valor_campo(campo, valor_raw):
    """Valida un valor según el tipo de campo. Retorna (valor_limpio, error)."""
    if not valor_raw:
        return '', None

    if campo.tipo == 'numero':
        num = normalizar_numero(valor_raw)
        if num is not None:
            return num, None
        return None, f'El campo "{campo.nombre}" debe ser un número válido.'

    if campo.tipo == 'moneda':
        moneda = normalizar_moneda(valor_raw)
        if moneda is not None:
            return moneda, None
        return None, f'El campo "{campo.nombre}" debe ser un valor monetario válido.'

    if campo.tipo == 'fecha':
        fecha = normalizar_fecha(valor_raw)
        if fecha is not None:
            return fecha, None
        if _es_fecha_serial(valor_raw):
            try:
                return _serial_a_fecha(float(valor_raw)), None
            except (ValueError, OverflowError):
                pass
        return None, f'El campo "{campo.nombre}" debe ser una fecha válida (YYYY-MM-DD).'

    if campo.tipo == 'booleano':
        bool_val = normalizar_booleano(valor_raw)
        if bool_val is not None:
            return bool_val, None
        return None, f'El campo "{campo.nombre}" debe ser un valor booleano válido (Sí/No/True/False/1/0).'

    if campo.tipo == 'lista' and campo.opciones:
        opciones_lista = [o.strip() for o in campo.opciones.split('\n') if o.strip()]
        if valor_raw not in opciones_lista:
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
        limpio = re.sub(r'[\s\-\+\(\)]', '', valor_raw)
        if not limpio.isdigit() or len(limpio) < 7:
            return None, f'El campo "{campo.nombre}" debe ser un teléfono válido (mín. 7 dígitos).'
        return valor_raw, None

    if campo.tipo == 'porcentaje':
        num = normalizar_numero(valor_raw)
        if num is not None:
            valor = num.replace('.', ',') if ',' not in num else num
            return valor, None
        return None, f'El campo "{campo.nombre}" debe ser un porcentaje válido (0-100).'

    if campo.tipo == 'hora':
        # HH:MM or HH:MM:SS
        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', valor_raw):
            parts = valor_raw.split(':')
            if 0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59:
                return valor_raw, None
        return None, f'El campo "{campo.nombre}" debe ser una hora válida (HH:MM).'

    if campo.tipo == 'fecha_hora':
        # YYYY-MM-DD HH:MM or DD/MM/YYYY HH:MM
        fecha = normalizar_fecha(valor_raw.split()[0]) if ' ' in valor_raw else None
        if fecha is None:
            return None, f'El campo "{campo.nombre}" debe ser una fecha y hora válida (YYYY-MM-DD HH:MM).'
        return f'{fecha} {valor_raw.split()[1] if len(valor_raw.split()) > 1 else "00:00"}', None

    if campo.tipo == 'documento':
        limpio = re.sub(r'[\s\-\.,]', '', valor_raw)
        if not limpio.isdigit() or len(limpio) < 5:
            return None, f'El campo "{campo.nombre}" debe ser un documento de identidad válido.'
        return valor_raw, None

    if campo.tipo == 'codigo':
        if len(valor_raw) < 2:
            return None, f'El campo "{campo.nombre}" debe ser un código válido.'
        return valor_raw, None

    if campo.tipo in ('codigo_barras', 'qr'):
        if len(valor_raw) < 3:
            return None, f'El campo "{campo.nombre}" debe contener un código válido.'
        return valor_raw, None

    if campo.tipo == 'color':
        if not re.match(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$', valor_raw):
            if not re.match(r'^(red|green|blue|black|white|yellow|orange|purple|pink|brown|gray|grey)$', valor_raw, re.IGNORECASE):
                return None, f'El campo "{campo.nombre}" debe ser un color válido (#HEX o nombre).'
        return valor_raw, None

    if campo.tipo == 'ip':
        # IPv4
        ip_match = re.match(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$', valor_raw)
        if ip_match:
            if all(0 <= int(g) <= 255 for g in ip_match.groups()):
                return valor_raw, None
        # IPv6 básico
        if ':' in valor_raw and len(valor_raw) <= 45:
            return valor_raw, None
        return None, f'El campo "{campo.nombre}" debe ser una IP válida (IPv4 o IPv6).'

    if campo.tipo == 'uuid':
        if not re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', valor_raw):
            return None, f'El campo "{campo.nombre}" debe ser un UUID válido.'
        return valor_raw, None

    if campo.tipo == 'geolocalizacion':
        # lat,lng format
        if ',' in valor_raw:
            parts = valor_raw.split(',')
            if len(parts) == 2:
                try:
                    lat = float(parts[0].strip())
                    lng = float(parts[1].strip())
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        return valor_raw, None
                except ValueError:
                    pass
        return None, f'El campo "{campo.nombre}" debe ser coordenadas válidas (lat, lng).'

    if campo.tipo == 'duracion':
        # HH:MM:SS or número + unidad
        if re.match(r'^\d{1,2}:\d{2}:\d{2}$', valor_raw):
            return valor_raw, None
        try:
            float(valor_raw.replace(',', '.'))
            return valor_raw, None
        except ValueError:
            pass
        return None, f'El campo "{campo.nombre}" debe ser una duración válida (HH:MM:SS o número).'

    if campo.tipo in ('estado', 'categoria'):
        if len(valor_raw) < 1:
            return None, f'El campo "{campo.nombre}" no puede estar vacío.'
        return valor_raw, None

    if campo.tipo == 'tags':
        # Comma or space separated tags
        if len(valor_raw) < 1:
            return None, f'El campo "{campo.nombre}" debe contener al menos una etiqueta.'
        return valor_raw, None

    if campo.tipo == 'relacion':
        if valor_raw.isdigit():
            ref_id = int(valor_raw)
            if not Registro.objects.filter(id=ref_id).exists():
                return None, f'El registro #{ref_id} referenciado en "{campo.nombre}" no existe.'
        return valor_raw, None

    if campo.tipo == 'calculado':
        return valor_raw, None

    return valor_raw, None
