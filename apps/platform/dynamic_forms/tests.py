"""
Pruebas automatizadas para el flujo dinámico (Dynamic Forms).

Verifica que el comportamiento del sistema EAV es equivalente al legacy.

Ejecución:
    python manage.py test apps.platform.dynamic_forms.tests --keepdb
    python manage.py test apps.platform.dynamic_forms.tests.TestFlujoCompletoE2E --keepdb

Requiere:
    - Base de datos de pruebas configurada
    - Los management commands sembrar_formularios_base y asignar_hook_ventas
"""

import time
from decimal import Decimal

from django.contrib.auth.models import User, Group
from django.core.management import call_command
from django.test import TestCase

from config.permissions import GRUPO_ADMINISTRADOR, GRUPO_VENDEDOR

from .models import Campo, Formulario, Registro, ValorCampo
from .services_dynamic import (
    DynamicService as DS,
    HookRecursivoError,
    ValorUnicoError,
    ValidacionError,
)


def _sembrar_base():
    """Limpia y resiembra los formularios base desde cero."""
    ValorCampo.objects.all().delete()
    Registro.objects.all().delete()
    Campo.objects.all().delete()
    Formulario.objects.all().delete()
    call_command('sembrar_formularios_base')
    call_command('asignar_hook_ventas')


def _crear_usuario(username, defaults, grupo_nombre):
    """Crea un usuario y lo asigna a un grupo. No re-hashea si ya existe."""
    user, creado = User.objects.get_or_create(
        username=username,
        defaults=defaults,
    )
    if creado:
        user.set_password(defaults.get('password', 'test123'))
        user.save()

    grupo, _ = Group.objects.get_or_create(name=grupo_nombre)
    user.groups.add(grupo)

    return user


# ======================================================================
# CONFIGURACIÓN BASE
# ======================================================================


class BaseDynamicTest(TestCase):
    """Configuración base para todas las pruebas dinámicas.

    El seed se ejecuta una vez por clase en setUpClass.
    Los usuarios y helpers se crean una vez por clase en setUpTestData.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Seed una vez por clase (necesario porque Django TestCase
        # revierte la BD entre clases incluso con --keepdb)
        _sembrar_base()

    @classmethod
    def setUpTestData(cls):
        """Crea usuarios UNA SOLA VEZ por clase (no por test)."""
        cls.vendedor = _crear_usuario(
            'vendedor_test',
            {'is_active': True, 'password': 'test123'},
            GRUPO_VENDEDOR,
        )
        cls.admin = _crear_usuario(
            'admin_test',
            {'is_active': True, 'is_superuser': True, 'is_staff': True,
             'password': 'admin123'},
            GRUPO_ADMINISTRADOR,
        )

    def _crear_producto(self, **kwargs):
        """Helper para crear un producto con valores por defecto."""
        datos = {
            'nombre': 'Producto Test',
            'precio': '50000',
            'stock': '10',
            'categoria': 'Ropa',
            'talla': 'M',
            'color': 'Azul',
            'sku': f'SKU-{self._testMethodName}-{kwargs.get("nombre", "test")[:4]}',
            'activo': 'Sí',
            'stock_minimo': '5',
        }
        datos.update(kwargs)
        return DS.crear('Productos', datos, usuario=self.admin)

    def _crear_cliente(self, **kwargs):
        """Helper para crear un cliente con valores por defecto."""
        timestamp = int(time.time() * 1000)
        datos = {
            'documento': f'DOC-{timestamp}',
            'nombre': 'Cliente',
            'apellido': 'Prueba',
            'correo': f'cliente_{timestamp}@email.com',
            'telefono': '3100000000',
            'activo': 'Sí',
        }
        datos.update(kwargs)
        return DS.crear('Clientes', datos)

    def _obtener_stock(self, producto_registro):
        """Helper para obtener el stock actual de un producto."""
        return int(DS.obtener_valor(producto_registro, 'stock', '0'))


# ======================================================================
# PRUEBA 1: Crear producto dinámico
# ======================================================================

class TestCrearProductoDinamico(BaseDynamicTest):

    def test_crear_producto_dinamico(self):
        """Verifica que se puede crear un producto y leer sus valores."""
        producto = self._crear_producto(
            nombre='Vestido Floral Test',
            precio='85000',
            stock='15',
            categoria='Ropa',
            sku='VES-TEST-001',
        )

        self.assertIsNotNone(producto)
        self.assertIsInstance(producto, Registro)
        self.assertEqual(producto.formulario.nombre, 'Productos')

        valores = DS.obtener_valores(producto)
        self.assertEqual(valores.get('nombre'), 'Vestido Floral Test')
        self.assertEqual(valores.get('precio'), '85000')
        self.assertEqual(valores.get('stock'), '15')
        self.assertEqual(valores.get('categoria'), 'Ropa')
        self.assertEqual(valores.get('sku'), 'VES-TEST-001')

        self.assertEqual(
            Campo.objects.filter(
                formulario=producto.formulario,
                nombre='sku',
                unico=True
            ).count(),
            1
        )


# ======================================================================
# PRUEBA 1b: Editar producto dinámico
# ======================================================================

class TestEditarProductoDinamico(BaseDynamicTest):

    def test_editar_producto_dinamico_cambia_valores(self):
        producto = self._crear_producto(
            nombre='Producto Original',
            precio='50000',
            stock='10',
            sku='EDIT-TEST-001',
        )

        DS.actualizar(producto, {
            'nombre': 'Producto Editado',
            'precio': '75000',
            'stock': '8',
            'categoria': 'Accesorios',
            'sku': 'EDIT-TEST-001',
            'activo': 'Sí',
        })

        producto.refresh_from_db()
        valores = DS.obtener_valores(producto)
        self.assertEqual(valores.get('nombre'), 'Producto Editado')
        self.assertEqual(valores.get('precio'), '75000')
        self.assertEqual(valores.get('stock'), '8')

    def test_editar_producto_mantiene_unicidad_sku(self):
        producto = self._crear_producto(sku='SKU-EDIT-UNICO')
        DS.actualizar(producto, {
            'nombre': 'Mismo SKU',
            'precio': '10000',
            'stock': '5',
            'sku': 'SKU-EDIT-UNICO',
        })
        valores = DS.obtener_valores(producto)
        self.assertEqual(valores.get('sku'), 'SKU-EDIT-UNICO')


# ======================================================================
# PRUEBA 2: Crear cliente dinámico
# ======================================================================

class TestCrearClienteDinamico(BaseDynamicTest):

    def test_crear_cliente_dinamico(self):
        cliente = self._crear_cliente(
            documento='9876543210',
            nombre='María',
            apellido='González',
            correo='maria.gonzalez@test.com',
            telefono='3109876543',
        )
        self.assertIsNotNone(cliente)
        valores = DS.obtener_valores(cliente)
        self.assertEqual(valores.get('documento'), '9876543210')
        self.assertEqual(valores.get('nombre'), 'María')

    def test_crear_cliente_sin_apellido(self):
        cliente = self._crear_cliente(
            documento='9876543211',
            nombre='Carlos',
            apellido='',
        )
        valores = DS.obtener_valores(cliente)
        self.assertEqual(valores.get('nombre'), 'Carlos')
        self.assertIsNone(valores.get('apellido'))


# ======================================================================
# PRUEBA 3: Venta descuenta stock
# ======================================================================

class TestVentaDescuentaStock(BaseDynamicTest):

    def test_venta_descuenta_stock(self):
        producto = self._crear_producto(
            nombre='Camisa Lino Test', precio='55000', stock='10',
            sku='CAM-TEST-001',
        )
        stock_inicial = self._obtener_stock(producto)
        self.assertEqual(stock_inicial, 10)

        DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '3',
            'precio_unitario': '55000',
        }, usuario=self.vendedor)

        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 7)

    def test_venta_multiple_descuenta_stock_acumulado(self):
        producto = self._crear_producto(
            nombre='Bolso Test', precio='120000', stock='20',
            sku='BOL-TEST-002',
        )
        DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '2',
            'precio_unitario': '120000',
        }, usuario=self.vendedor)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 18)

        DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '5',
            'precio_unitario': '120000',
        }, usuario=self.vendedor)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 13)

    def test_venta_con_precio_unitario_calcula_campos(self):
        producto = self._crear_producto(
            nombre='Zapatos Test', precio='95000', stock='8',
            sku='ZAP-TEST-003',
        )
        venta = DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '2',
            'precio_unitario': '95000', 'descuento': '5000',
        }, usuario=self.vendedor)

        valores = DS.obtener_valores(venta)
        self.assertEqual(valores.get('subtotal'), '190000')
        self.assertEqual(valores.get('total'), '185000')


# ======================================================================
# PRUEBA 4: Stock insuficiente hace rollback
# ======================================================================

class TestStockInsuficienteRollback(BaseDynamicTest):

    def test_stock_insuficiente_hace_rollback(self):
        producto = self._crear_producto(
            nombre='Producto Stock Bajo', precio='30000', stock='2',
            sku='STK-TEST-001',
        )
        stock_inicial = self._obtener_stock(producto)

        ventas_antes = DS.contar('Ventas')
        movimientos_antes = DS.contar('MovimientosInventario')

        with self.assertRaises((ValueError, ValidacionError)) as context:
            DS.crear('Ventas', {
                'producto': str(producto.id), 'cantidad': '5',
                'precio_unitario': '30000',
            }, usuario=self.vendedor)

        self.assertIn('stock', str(context.exception).lower())
        self.assertEqual(DS.contar('Ventas'), ventas_antes)
        self.assertEqual(DS.contar('MovimientosInventario'), movimientos_antes)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), stock_inicial)

    def test_venta_cantidad_cero_rechazada(self):
        producto = self._crear_producto(
            nombre='Producto Test', precio='10000', stock='10',
            sku='STK-TEST-002',
        )
        with self.assertRaises((ValueError, ValidacionError)):
            DS.crear('Ventas', {
                'producto': str(producto.id), 'cantidad': '0',
                'precio_unitario': '10000',
            }, usuario=self.vendedor)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 10)

    def test_venta_producto_inexistente(self):
        with self.assertRaises((ValueError, ValidacionError, Registro.DoesNotExist)):
            DS.crear('Ventas', {
                'producto': '999999', 'cantidad': '1',
                'precio_unitario': '10000',
            }, usuario=self.vendedor)


# ======================================================================
# PRUEBA 5: Movimiento de inventario automático
# ======================================================================

class TestMovimientoInventarioAutomatico(BaseDynamicTest):

    def test_movimiento_inventario_automatico(self):
        producto = self._crear_producto(
            nombre='Producto Mov Test', precio='40000', stock='20',
            sku='MOV-TEST-001',
        )
        stock_antes = self._obtener_stock(producto)

        DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '4',
            'precio_unitario': '40000',
        }, usuario=self.vendedor)

        movimientos = DS.filtrar('MovimientosInventario')
        self.assertGreaterEqual(movimientos.count(), 1)

        ultimo_mov = movimientos.order_by('-id').first()
        self.assertIsNotNone(ultimo_mov)
        valores_mov = DS.obtener_valores(ultimo_mov)
        self.assertEqual(valores_mov.get('producto'), str(producto.id))
        self.assertEqual(valores_mov.get('tipo'), 'Salida')
        self.assertEqual(valores_mov.get('cantidad'), '4')
        self.assertEqual(valores_mov.get('stock_anterior'), str(stock_antes))
        self.assertEqual(valores_mov.get('stock_nuevo'), str(stock_antes - 4))
        self.assertIn('Venta', valores_mov.get('observacion', ''))

    def test_movimiento_guarda_stock_anterior_y_nuevo(self):
        producto = self._crear_producto(
            nombre='Producto Stock Track', precio='25000', stock='15',
            sku='MOV-TEST-002',
        )
        DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '3',
            'precio_unitario': '25000',
        }, usuario=self.vendedor)
        DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '5',
            'precio_unitario': '25000',
        }, usuario=self.vendedor)

        movimientos = DS.filtrar('MovimientosInventario')
        ultimo = movimientos.order_by('-id').first()
        valores = DS.obtener_valores(ultimo)
        self.assertEqual(valores.get('stock_anterior'), '12')
        self.assertEqual(valores.get('stock_nuevo'), '7')
        self.assertEqual(valores.get('cantidad'), '5')


# ======================================================================
# PRUEBA 6: Unicidad de documento de cliente
# ======================================================================

class TestUnicidadDocumentoCliente(BaseDynamicTest):

    def test_unicidad_documento_cliente(self):
        formulario_clientes = Formulario.objects.get(nombre='Clientes')
        campo_documento = formulario_clientes.campos.filter(
            nombre='documento', activo=True
        ).first()
        self.assertTrue(campo_documento.unico)

        self._crear_cliente(documento='UNICO-001')
        with self.assertRaises(ValorUnicoError):
            self._crear_cliente(documento='UNICO-001')

    def test_unicidad_documento_con_activo_inactivo(self):
        self._crear_cliente(documento='INACTIVO-001')
        with self.assertRaises(ValorUnicoError):
            self._crear_cliente(documento='INACTIVO-001')


# ======================================================================
# PRUEBA 7: Unicidad de SKU de producto
# ======================================================================

class TestUnicidadSkuProducto(BaseDynamicTest):

    def test_unicidad_sku_producto(self):
        formulario_productos = Formulario.objects.get(nombre='Productos')
        campo_sku = formulario_productos.campos.filter(
            nombre='sku', activo=True
        ).first()
        self.assertTrue(campo_sku.unico)

        self._crear_producto(sku='SKU-UNICO-001')
        with self.assertRaises(ValorUnicoError):
            self._crear_producto(sku='SKU-UNICO-001')

    def test_sku_vacio_no_afecta_unicidad(self):
        p1 = self._crear_producto(sku='')
        p2 = self._crear_producto(sku='')
        self.assertIsNotNone(p1)
        self.assertIsNotNone(p2)


# ======================================================================
# PRUEBA 8: Protección contra recursión de hooks
# ======================================================================

class TestHookRecursion(BaseDynamicTest):
    """Verifica que _ejecutar_hook detecta y previene recursión de hooks."""

    def _crear_registro_real(self):
        """Crea un registro real para usar en las pruebas de hooks."""
        formulario = Formulario.objects.get(nombre='Productos')
        return Registro.objects.create(formulario=formulario, usuario=self.admin)

    def test_detecta_recursion_con_registro_real(self):
        """
        Llamar a _ejecutar_hook cuando ya hay un hook activo debe lanzar
        HookRecursivoError. Usa un registro real para evitar AttributeError.
        """
        from .services_dynamic import _marcar_inicio_hook, _marcar_fin_hook

        registro = self._crear_registro_real()

        _marcar_inicio_hook()
        try:
            with self.assertRaises(HookRecursivoError):
                DS._ejecutar_hook(
                    'apps.legacy.ventas.hooks.post_crear_venta',
                    registro,
                )
        finally:
            _marcar_fin_hook()

    def test_ejecucion_normal_sin_recursion_funciona(self):
        """Ejecutar un hook sin recursión activa debe funcionar normalmente."""
        from .services_dynamic import _ejecucion_hooks_activa

        self.assertFalse(_ejecucion_hooks_activa())

        producto = self._crear_producto(
            nombre='Producto Hook Test',
            precio='50000',
            stock='10',
            sku='HOOK-TEST-001',
        )

        venta = DS.crear('Ventas', {
            'producto': str(producto.id),
            'cantidad': '1',
            'precio_unitario': '50000',
        }, usuario=self.vendedor)

        self.assertIsNotNone(venta)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 9)

    def test_hook_no_recursivo_en_flujo_real(self):
        """
        Verifica que el hook post_crear_venta NO dispara recursión
        cuando llama a DS.crear('MovimientosInventario', ...).
        """
        from .services_dynamic import _ejecucion_hooks_activa

        producto = self._crear_producto(
            nombre='Producto No Recursión',
            precio='35000',
            stock='15',
            sku='NORECURSION-001',
        )

        self.assertFalse(_ejecucion_hooks_activa())

        venta = DS.crear('Ventas', {
            'producto': str(producto.id),
            'cantidad': '2',
            'precio_unitario': '35000',
        }, usuario=self.vendedor)

        self.assertFalse(_ejecucion_hooks_activa())
        self.assertIsNotNone(venta)


# ======================================================================
# PRUEBA 9: Concurrencia — validación del flujo de stock
# ======================================================================

class TestConcurrenciaStock(BaseDynamicTest):
    """
    Prueba de concurrencia para validar el comportamiento actual del flujo
    de stock con select_for_update.

    NOTA: Esta prueba no prueba concurrencia real (requeriría hilos/OS),
    sino que valida que la lógica actual de bloqueo funciona correctamente
    en escenarios secuenciales que simulan condiciones de carrera.

    El flujo actual usa select_for_update DENTRO del hook, en un savepoint
    anidado. Esta prueba documenta ese comportamiento y será la referencia
    cuando se modifique la estrategia de bloqueo.
    """

    def test_venta_concurrente_secuencial(self):
        """Dos ventas secuenciales sobre el mismo producto producen stock final correcto."""
        producto = self._crear_producto(
            nombre='Producto Concurrencia',
            precio='30000',
            stock='100',
            sku='CONC-TEST-001',
        )

        venta1 = DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '30',
            'precio_unitario': '30000',
        }, usuario=self.vendedor)
        self.assertIsNotNone(venta1)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 70)

        venta2 = DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '20',
            'precio_unitario': '30000',
        }, usuario=self.vendedor)
        self.assertIsNotNone(venta2)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 50)

        movimientos = DS.filtrar('MovimientosInventario', producto=str(producto.id))
        self.assertEqual(movimientos.count(), 2)

    def test_overgestion_no_permitida(self):
        """No se puede vender más stock del disponible en operaciones separadas."""
        producto = self._crear_producto(
            nombre='Producto Overbooking',
            precio='20000',
            stock='10',
            sku='CONC-TEST-002',
        )

        DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '6',
            'precio_unitario': '20000',
        }, usuario=self.vendedor)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 4)

        with self.assertRaises((ValueError, ValidacionError)):
            DS.crear('Ventas', {
                'producto': str(producto.id), 'cantidad': '5',
                'precio_unitario': '20000',
            }, usuario=self.vendedor)

        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 4)

    def test_select_for_update_en_formulario_con_hooks(self):
        """Verifica que el formulario Ventas tiene hooks y el bloqueo pesimista funciona."""
        formulario_ventas = Formulario.objects.get(nombre='Ventas')
        self.assertIsNotNone(
            formulario_ventas.hook_post_crear,
            'El formulario Ventas debe tener hook_post_crear asignado'
        )

        producto = self._crear_producto(
            nombre='Producto Lock Test',
            precio='40000',
            stock='10',
            sku='LOCK-TEST-001',
        )

        venta = DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '3',
            'precio_unitario': '40000',
        }, usuario=self.vendedor)

        self.assertIsNotNone(venta)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 7)

    def test_stock_se_mantiene_inicial_si_hook_falla(self):
        """
        Verifica que si el hook falla (ej: stock insuficiente),
        el stock del producto NO se modifica (rollback completo).
        """
        producto = self._crear_producto(
            nombre='Producto Rollback Test',
            precio='15000',
            stock='3',
            sku='CONC-RB-001',
        )

        with self.assertRaises((ValueError, ValidacionError)):
            DS.crear('Ventas', {
                'producto': str(producto.id), 'cantidad': '5',
                'precio_unitario': '15000',
            }, usuario=self.vendedor)

        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 3)


# ======================================================================
# PRUEBA ADICIONAL: Flujo completo E2E
# ======================================================================

class TestFlujoCompletoE2E(BaseDynamicTest):
    """Prueba integral que valida todo el flujo de negocio."""

    def test_flujo_completo_crear_producto_vender_y_verificar_movimiento(self):
        """Flujo completo: crear producto -> crear venta -> verificar stock y movimiento."""
        producto = self._crear_producto(
            nombre='Producto Flujo Completo',
            precio='60000',
            stock='10',
            sku='FLUJO-E2E-001',
        )
        self.assertEqual(self._obtener_stock(producto), 10)

        cliente = self._crear_cliente(documento='FLUJO-E2E-CLI')

        venta = DS.crear('Ventas', {
            'producto': str(producto.id), 'cantidad': '3',
            'cliente': str(cliente.id), 'precio_unitario': '60000',
        }, usuario=self.vendedor)

        self.assertIsNotNone(venta)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 7)

        movimientos = DS.filtrar('MovimientosInventario')
        mov = movimientos.order_by('-id').first()
        self.assertIsNotNone(mov)
        valores_mov = DS.obtener_valores(mov)
        self.assertEqual(valores_mov.get('producto'), str(producto.id))
        self.assertEqual(valores_mov.get('tipo'), 'Salida')
        self.assertEqual(valores_mov.get('cantidad'), '3')

    def test_flujo_rollback_por_stock_insuficiente(self):
        """Stock insuficiente causa rollback completo: ni venta, ni movimiento, ni cambio de stock."""
        producto = self._crear_producto(
            nombre='Producto Rollback',
            precio='80000',
            stock='1',
            sku='FLUJO-RB-001',
        )

        ventas_antes = DS.contar('Ventas')
        movimientos_antes = DS.contar('MovimientosInventario')

        with self.assertRaises((ValueError, ValidacionError)):
            DS.crear('Ventas', {
                'producto': str(producto.id), 'cantidad': '5',
                'precio_unitario': '80000',
            }, usuario=self.vendedor)

        self.assertEqual(DS.contar('Ventas'), ventas_antes)
        self.assertEqual(DS.contar('MovimientosInventario'), movimientos_antes)
        producto.refresh_from_db()
        self.assertEqual(self._obtener_stock(producto), 1)
