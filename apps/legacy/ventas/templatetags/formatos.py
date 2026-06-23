from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()


def _normalizar_decimal(value):
    if value is None or value == '':
        return Decimal('0')

    if isinstance(value, Decimal):
        return value

    texto = str(value).strip()

    if not texto:
        return Decimal('0')

    texto = (
        texto
        .replace('$', '')
        .replace('COP', '')
        .replace('\xa0', '')
        .replace(' ', '')
    )

    if ',' in texto and '.' in texto:
        texto = texto.replace('.', '').replace(',', '.')
    elif ',' in texto:
        texto = texto.replace(',', '.')

    try:
        return Decimal(texto)
    except (InvalidOperation, ValueError):
        return Decimal('0')


@register.filter
def formato_pesos(value):
    numero = _normalizar_decimal(value)
    numero_entero = int(numero.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    signo = '-' if numero_entero < 0 else ''
    numero_absoluto = abs(numero_entero)

    return f'{signo}${numero_absoluto:,}'.replace(',', '.')


@register.filter
def formato_numero(value):
    numero = _normalizar_decimal(value)
    numero_entero = int(numero.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    signo = '-' if numero_entero < 0 else ''
    numero_absoluto = abs(numero_entero)

    return f'{signo}{numero_absoluto:,}'.replace(',', '.')