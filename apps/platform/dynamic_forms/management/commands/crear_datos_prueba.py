"""
Management command para crear datos de prueba completos para el flujo dinámico.

Uso:
    python manage.py crear_datos_prueba
    python manage.py crear_datos_prueba --ventas 5

Crea:
    - Formularios base (Productos, Clientes, Ventas, MovimientosInventario)
    - Hook post_crear_venta asignado al formulario Ventas
    - 5 productos con categorías variadas
    - 5 clientes con documentos únicos
    - N ventas (por defecto 3) que generan automáticamente movimientos de inventario
"""

import logging
import random

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group

from config.permissions import GRUPO_ADMINISTRADOR, GRUPO_VENDEDOR

from ...models import Formulario
from ...services_dynamic import DynamicService as DS

logger = logging.getLogger(__name__)


# ======================================================================
# DATOS DE PRUEBA
# ======================================================================

PRODUCTOS_EJEMPLO = [
    {
        'nombre': 'Vestido Floral Primavera',
        'precio': '85000',
        'stock': '15',
        'categoria': 'Ropa',
        'talla': 'M',
        'color': 'Rosado',
        'sku': 'VES-001',
        'descripcion': 'Vestido estampado floral, fresco y ligero ideal para primavera.',
        'stock_minimo': '5',
        'activo': 'Sí',
    },
    {
        'nombre': 'Camisa Lino Blanca',
        'precio': '55000',
        'stock': '10',
        'categoria': 'Ropa',
        'talla': 'L',
        'color': 'Blanco',
        'sku': 'CAM-002',
        'descripcion': 'Camisa de lino 100% algodón, manga larga.',
        'stock_minimo': '3',
        'activo': 'Sí',
    },
    {
        'nombre': 'Bolso Cuero Marrón',
        'precio': '120000',
        'stock': '5',
        'categoria': 'Accesorios',
        'talla': 'Unica',
        'color': 'Marrón',
        'sku': 'BOL-003',
        'descripcion': 'Bolso artesanal en cuero genuino con cierre dorado.',
        'stock_minimo': '2',
        'activo': 'Sí',
    },
    {
        'nombre': 'Zapatos Tacón Negro',
        'precio': '95000',
        'stock': '8',
        'categoria': 'Calzado',
        'talla': '38',
        'color': 'Negro',
        'sku': 'ZAP-004',
        'descripcion': 'Tacón punta fina, suela antideslizante.',
        'stock_minimo': '3',
        'activo': 'Sí',
    },
    {
        'nombre': 'Reloj Deportivo Digital',
        'precio': '45000',
        'stock': '20',
        'categoria': 'Accesorios',
        'talla': 'Ajustable',
        'color': 'Gris',
        'sku': 'REL-005',
        'descripcion': 'Reloj resistente al agua con cronómetro y alarma.',
        'stock_minimo': '5',
        'activo': 'Sí',
    },
]

CLIENTES_EJEMPLO = [
    {
        'documento': '1012345678',
        'nombre': 'María',
        'apellido': 'González López',
        'correo': 'maria.gonzalez@email.com',
        'telefono': '3101234567',
        'direccion': 'Calle 10 # 20-30, Bogotá',
        'activo': 'Sí',
    },
    {
        'documento': '1023456789',
        'nombre': 'Carlos',
        'apellido': 'Mendoza Pérez',
        'correo': 'carlos.mendoza@email.com',
        'telefono': '3102345678',
        'direccion': 'Carrera 15 # 40-50, Medellín',
        'activo': 'Sí',
    },
    {
        'documento': '1034567890',
        'nombre': 'Ana',
        'apellido': 'Rodríguez Silva',
        'correo': 'ana.rodriguez@email.com',
        'telefono': '3103456789',
        'direccion': 'Avenida 5 # 10-20, Cali',
        'activo': 'Sí',
    },
    {
        'documento': '1045678901',
        'nombre': 'Pedro',
        'apellido': 'Martínez Rojas',
        'correo': 'pedro.martinez@email.com',
        'telefono': '3104567890',
        'direccion': 'Calle 25 # 30-40, Barranquilla',
        'activo': 'No',
    },
    {
        'documento': '1056789012',
        'nombre': 'Laura',
        'apellido': 'Hernández Castro',
        'correo': 'laura.hernandez@email.com',
        'telefono': '3105678901',
        'direccion': 'Carrera 8 # 15-25, Cartagena',
        'activo': 'Sí',
    },
]

VENDEDOR_USERNAME = 'vendedor_prueba'
VENDEDOR_PASSWORD = 'Prueba123!'


def _crear_o_actualizar_usuario(username, password, grupo_nombre, **extra):
    """Crea un usuario y lo agrega a un grupo."""
    user, creado = User.objects.get_or_create(
        username=username,
        defaults={
            'is_active': True,
            **extra,
        }
    )
    if creado:
        user.set_password(password)
        user.save()

    grupo, _ = Group.objects.get_or_create(name=grupo_nombre)
    user.groups.add(grupo)

    return user, creado


class Command(BaseCommand):
    help = 'Crea datos de prueba completos para el flujo dinámico.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--ventas', type=int, default=3,
            help='Número de ventas a crear (por defecto: 3)'
        )
        parser.add_argument(
            '--admin', action='store_true',
            help='Crear también un usuario administrador'
        )

    def handle(self, *args, **options):
        total_ventas = options['ventas']
        crear_admin = options['admin']

        self.stdout.write(self.style.MIGRATE_HEADING(
            '=== Creando datos de prueba para flujo dinámico ==='
        ))
        self.stdout.write('')

        # ------------------------------------------------------------------
        # 1. Sembrar formularios base
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL('[1/6] Sembrando formularios base...'))
        call_command('sembrar_formularios_base')
        self.stdout.write(self.style.SUCCESS('  ✓ Formularios base listos.'))

        # ------------------------------------------------------------------
        # 2. Asignar hook post_crear a Ventas
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL('[2/6] Asignando hook post_crear a Ventas...'))
        call_command('asignar_hook_ventas')
        self.stdout.write(self.style.SUCCESS('  ✓ Hook asignado.'))

        # ------------------------------------------------------------------
        # 3. Crear vendedor de prueba
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL('[3/6] Creando vendedor de prueba...'))
        vendedor, creado = _crear_o_actualizar_usuario(
            VENDEDOR_USERNAME,
            VENDEDOR_PASSWORD,
            GRUPO_VENDEDOR,
            first_name='Vendedor',
            last_name='Prueba',
            email='vendedor@tonjeo.app',
        )
        self.stdout.write(f'  ✓ Vendedor: "{VENDEDOR_USERNAME}" / "{VENDEDOR_PASSWORD}"')

        if crear_admin:
            admin_user, _ = _crear_o_actualizar_usuario(
                'admin_prueba',
                'Admin123!',
                GRUPO_ADMINISTRADOR,
                first_name='Admin',
                last_name='Prueba',
                is_superuser=True,
                email='admin@tonjeo.app',
            )
            admin_user.is_staff = True
            admin_user.save(update_fields=['is_staff'])
            self.stdout.write(f'  ✓ Admin: "admin_prueba" / "Admin123!"')

        # ------------------------------------------------------------------
        # 4. Crear 5 productos
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL('[4/6] Creando 5 productos...'))
        productos_creados = []
        for prod_data in PRODUCTOS_EJEMPLO:
            try:
                registro = DS.crear('Productos', prod_data)
                productos_creados.append(registro)
                self.stdout.write(
                    f'  ✓ Producto #{registro.id}: {prod_data["nombre"]} '
                    f'(${prod_data["precio"]}, stock: {prod_data["stock"]})'
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ Error creando producto "{prod_data["nombre"]}": {e}'
                ))

        if not productos_creados:
            self.stdout.write(self.style.ERROR(
                '  ✗ No se pudo crear ningún producto. Abortando.'
            ))
            return

        # ------------------------------------------------------------------
        # 5. Crear 5 clientes
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL('[5/6] Creando 5 clientes...'))
        clientes_creados = []
        for cli_data in CLIENTES_EJEMPLO:
            try:
                registro = DS.crear('Clientes', cli_data)
                clientes_creados.append(registro)
                self.stdout.write(
                    f'  ✓ Cliente #{registro.id}: {cli_data["nombre"]} {cli_data["apellido"]}'
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ Error creando cliente "{cli_data["nombre"]}": {e}'
                ))

        # ------------------------------------------------------------------
        # 6. Crear ventas de prueba (generan movimientos automáticamente)
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL(
            f'[6/6] Creando {total_ventas} ventas de prueba...'
        ))

        ventas_creadas = 0
        for i in range(total_ventas):
            if not productos_creados or not clientes_creados:
                self.stdout.write(self.style.WARNING(
                    '  ⚠ No hay suficientes productos o clientes para crear ventas.'
                ))
                break

            producto = productos_creados[i % len(productos_creados)]
            cliente = clientes_creados[i % len(clientes_creados)]

            # Cantidad aleatoria entre 1 y 3, asegurando stock suficiente
            max_stock = int(
                DS.obtener_valor(producto, 'stock', '0')
            )
            if max_stock <= 0:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ Producto #{producto.id} sin stock, saltando venta.'
                ))
                continue

            cantidad = min(random.randint(1, 3), max_stock)

            try:
                # Obtener el precio para calcular
                precio = DS.obtener_valor(producto, 'precio', '0')

                DS.crear('Ventas', {
                    'producto': str(producto.id),
                    'cantidad': str(cantidad),
                    'cliente': str(cliente.id),
                    'precio_unitario': precio,
                }, usuario=vendedor)

                # Recargar producto para ver stock actualizado
                producto.refresh_from_db()
                stock_restante = DS.obtener_valor(producto, 'stock', '0')
                ventas_creadas += 1
                self.stdout.write(
                    f'  ✓ Venta #{ventas_creadas}: {cantidad}x Producto #{producto.id} '
                    f'(stock restante: {stock_restante})'
                )

            except Exception as e:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ Error en venta {i + 1}: {e}'
                ))

        # ------------------------------------------------------------------
        # Resumen final
        # ------------------------------------------------------------------
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('  ¡DATOS DE PRUEBA CREADOS EXITOSAMENTE!'))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write('')
        self.stdout.write(f'  Productos creados:       {len(productos_creados)}')
        self.stdout.write(f'  Clientes creados:         {len(clientes_creados)}')
        self.stdout.write(f'  Ventas creadas:           {ventas_creadas}')
        self.stdout.write(f'  Vendedor:                 {VENDEDOR_USERNAME} / {VENDEDOR_PASSWORD}')

        if crear_admin:
            self.stdout.write(f'  Admin:                    admin_prueba / Admin123!')

        # Mostrar formulario de Ventas con hook
        try:
            form_ventas = Formulario.objects.get(nombre='Ventas')
            self.stdout.write(f'  Hook post_crear Ventas:    {form_ventas.hook_post_crear or "NO ASIGNADO"}')
        except Formulario.DoesNotExist:
            pass

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_LABEL(
            'Para ejecutar las pruebas automatizadas: python manage.py test '
            'apps.platform.dynamic_forms.tests --keepdb'
        ))
