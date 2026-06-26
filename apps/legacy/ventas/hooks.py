"""
Hooks para el formulario de Ventas.

Estas funciones se ejecutan automaticamente cuando se crea o actualiza
un registro en el formulario "Ventas" a traves de DynamicService o
de la vista llenar_formulario (con dispatch de hooks).

Requiere que el formulario "Ventas" tenga configurado:
    hook_post_crear = "apps.legacy.ventas.hooks.post_crear_venta"
"""

import logging
from decimal import Decimal

from django.db import transaction

from apps.platform.dynamic_forms.models import Campo, Formulario, Registro, ValorCampo
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

logger = logging.getLogger(__name__)


# ======================================================================
# HOOK POST-CREAR VENTA
# ======================================================================


def post_crear_venta(registro_venta):
    """
    Hook ejecutado despues de crear un registro en el formulario "Ventas".

    Flujo:
        1. Obtener producto (ID del registro en Productos), cantidad y precio_unitario.
        2. Validar que el producto exista y tenga stock suficiente.
        3. Bloquear el registro del producto (select_for_update).
        4. Descontar stock: stock_nuevo = stock_actual - cantidad.
        5. Crear registro en MovimientosInventario.
        6. Si algo falla, la transaccion hace rollback completo.

    Args:
        registro_venta: Instancia de Registro (formulario="Ventas")

    Raises:
        ValueError: Si el producto no existe o no hay stock suficiente.
        Exception: Cualquier error causa rollback.
    """
    logger.info(f'Hook post_crear_venta ejecutandose para registro #{registro_venta.id}')

    # ------------------------------------------------------------------
    # 1. Leer valores de la venta
    # ------------------------------------------------------------------
    valores = DS.obtener_valores(registro_venta)

    producto_id_raw = valores.get('producto', '').strip()
    cantidad_raw = valores.get('cantidad', '').strip()
    precio_unitario_raw = valores.get('precio_unitario', '').strip()

    if not producto_id_raw or not producto_id_raw.isdigit():
        raise ValueError('La venta no tiene un producto valido asignado.')

    if not cantidad_raw:
        raise ValueError('La venta no tiene una cantidad asignada.')

    try:
        cantidad = int(cantidad_raw)
    except (ValueError, TypeError):
        raise ValueError(f'La cantidad "{cantidad_raw}" no es un numero entero valido.')

    if cantidad <= 0:
        raise ValueError('La cantidad debe ser mayor a 0.')

    producto_id = int(producto_id_raw)

    # ------------------------------------------------------------------
    # 2. Buscar el formulario y registro del producto
    # ------------------------------------------------------------------
    try:
        form_productos = Formulario.objects.get(nombre='Productos')
    except Formulario.DoesNotExist:
        raise ValueError('No existe el formulario "Productos". Ejecuta el seed primero.')

    try:
        registro_producto = Registro.objects.get(
            id=producto_id,
            formulario=form_productos
        )
    except Registro.DoesNotExist:
        raise ValueError(f'El producto #{producto_id} no existe en el formulario Productos.')

    # ------------------------------------------------------------------
    # 3. Bloquear producto y validar stock (DENTRO de la transaccion)
    # ------------------------------------------------------------------
    # Nota: Este hook se ejecuta dentro de la transaccion de llenar_formulario
    # o DynamicService.crear(), por lo que select_for_update funciona.

    with transaction.atomic():
        # Bloquear el registro del producto para evitar condiciones de carrera
        registro_bloqueado = Registro.objects.select_for_update().get(
            id=producto_id,
            formulario=form_productos
        )

        # Obtener stock actual
        stock_actual_raw = DS.obtener_valor(registro_bloqueado, 'stock', '0')
        try:
            stock_actual = int(stock_actual_raw)
        except (ValueError, TypeError):
            stock_actual = 0

        # Validar stock suficiente
        if stock_actual < cantidad:
            raise ValueError(
                f'Stock insuficiente para el producto #{producto_id}. '
                f'Disponible: {stock_actual}, solicitado: {cantidad}.'
            )

        stock_nuevo = stock_actual - cantidad

        # ------------------------------------------------------------------
        # 4. Actualizar stock del producto
        # ------------------------------------------------------------------
        # Buscar el campo 'stock' en el formulario Productos
        try:
            campo_stock = Campo.objects.get(
                formulario=form_productos,
                nombre='stock',
                activo=True
            )
        except Campo.DoesNotExist:
            raise ValueError('El formulario Productos no tiene un campo "stock".')

        ValorCampo.objects.update_or_create(
            registro=registro_bloqueado,
            campo=campo_stock,
            defaults={'valor': str(stock_nuevo)}
        )

        # ------------------------------------------------------------------
        # 5. Crear registro en MovimientosInventario
        # ------------------------------------------------------------------
        try:
            form_movimientos = Formulario.objects.get(nombre='MovimientosInventario')
        except Formulario.DoesNotExist:
            raise ValueError(
                'No existe el formulario "MovimientosInventario". '
                'Ejecuta el seed primero.'
            )

        # Obtener o crear el campo 'precio_unitario' en la venta si no tiene valor
        # Esto permite calcular el total correctamente
        if not precio_unitario_raw:
            # Intentar obtener el precio del producto
            precio_raw = DS.obtener_valor(registro_bloqueado, 'precio', '0')
            try:
                precio_val = Decimal(str(precio_raw).replace(',', '.'))
                precio_unitario_raw = str(precio_val)
            except (ValueError, TypeError):
                precio_unitario_raw = '0'

            # Guardar precio_unitario en la venta si se pudo obtener
            if precio_unitario_raw != '0':
                try:
                    campo_precio_unitario = Campo.objects.get(
                        formulario=registro_venta.formulario,
                        nombre='precio_unitario',
                        activo=True
                    )
                    ValorCampo.objects.update_or_create(
                        registro=registro_venta,
                        campo=campo_precio_unitario,
                        defaults={'valor': precio_unitario_raw}
                    )
                except Campo.DoesNotExist:
                    pass  # Si no existe el campo, continuar sin el

        # Crear movimiento de inventario
        DS.crear('MovimientosInventario', {
            'producto': str(producto_id),
            'tipo': 'Salida',
            'cantidad': str(cantidad),
            'motivo': 'Venta del sistema',
            'stock_anterior': str(stock_actual),
            'stock_nuevo': str(stock_nuevo),
            'observacion': f'Venta #{registro_venta.id} - Descuento automatico por venta.',
        })

        logger.info(
            f'Venta #{registro_venta.id}: Producto #{producto_id} '
            f'stock {stock_actual} -> {stock_nuevo} '
            f'(cantidad: {cantidad})'
        )
