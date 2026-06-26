"""
Management command para sembrar los formularios base del sistema.

Uso:
    python manage.py sembrar_formularios_base

Este comando crea los 4 formularios fundamentales sobre los que se
construye toda la lógica de negocio:

    1. Productos
    2. Clientes
    3. Ventas
    4. MovimientosInventario

Es seguro ejecutarlo múltiples veces: no duplica formularios ni campos
existentes (usa get_or_create por nombre de formulario).
"""

from django.core.management.base import BaseCommand

from ...models import Campo, Formulario


# ======================================================================
# DEFINICIÓN DE FORMULARIOS BASE
# ======================================================================
# Cada formulario se define con:
#   nombre: str
#   descripcion: str
#   campos: list of dict con:
#       nombre, tipo, obligatorio, orden, unico, opciones (opcional),
#       formula (opcional), formulario_destino_nombre (opcional)

FORMULARIOS_BASE = [
    {
        'nombre': 'Productos',
        'descripcion': 'Registro de productos del sistema. Cada producto se crea como un registro en este formulario.',
        'campos': [
            {'nombre': 'nombre',          'tipo': 'texto',    'obligatorio': True,  'orden': 1},
            {'nombre': 'precio',          'tipo': 'numero',   'obligatorio': True,  'orden': 2},
            {'nombre': 'stock',           'tipo': 'numero',   'obligatorio': True,  'orden': 3},
            {'nombre': 'categoria',       'tipo': 'lista',    'obligatorio': False, 'orden': 4,
             'opciones': ['Ropa', 'Accesorios', 'Calzado', 'Hogar', 'Tecnologia', 'Otros']},
            {'nombre': 'descripcion',     'tipo': 'textarea', 'obligatorio': False, 'orden': 5},
            {'nombre': 'sku',             'tipo': 'texto',    'obligatorio': False, 'orden': 6, 'unico': True},
            {'nombre': 'talla',           'tipo': 'lista',    'obligatorio': False, 'orden': 7,
             'opciones': ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'Unica', 'Ajustable']},
            {'nombre': 'color',           'tipo': 'texto',    'obligatorio': False, 'orden': 8},
            {'nombre': 'imagen',          'tipo': 'imagen',   'obligatorio': False, 'orden': 9},
            {'nombre': 'imagen_url',      'tipo': 'url',      'obligatorio': False, 'orden': 10},
            {'nombre': 'stock_minimo',    'tipo': 'numero',   'obligatorio': False, 'orden': 11},
            {'nombre': 'activo',          'tipo': 'booleano', 'obligatorio': False, 'orden': 12},
        ],
    },
    {
        'nombre': 'Clientes',
        'descripcion': 'Registro de clientes del sistema.',
        'campos': [
            {'nombre': 'documento',       'tipo': 'texto',    'obligatorio': True,  'orden': 1, 'unico': True},
            {'nombre': 'nombre',          'tipo': 'texto',    'obligatorio': True,  'orden': 2},
            {'nombre': 'apellido',        'tipo': 'texto',    'obligatorio': False, 'orden': 3},
            {'nombre': 'correo',          'tipo': 'email',    'obligatorio': False, 'orden': 4},
            {'nombre': 'telefono',        'tipo': 'telefono', 'obligatorio': False, 'orden': 5},
            {'nombre': 'direccion',       'tipo': 'texto',    'obligatorio': False, 'orden': 6},
            {'nombre': 'activo',          'tipo': 'booleano', 'obligatorio': False, 'orden': 7},
        ],
    },        {
        'nombre': 'Ventas',
        'descripcion': 'Registro de ventas. Se relaciona con Productos y Clientes.',
        'campos': [
            {'nombre': 'producto',        'tipo': 'relacion', 'obligatorio': True,  'orden': 1,
             'formulario_destino_nombre': 'Productos'},
            {'nombre': 'cantidad',        'tipo': 'numero',   'obligatorio': True,  'orden': 2},
            {'nombre': 'cliente',         'tipo': 'relacion', 'obligatorio': False, 'orden': 3,
             'formulario_destino_nombre': 'Clientes'},
            {'nombre': 'subtotal',        'tipo': 'calculado','obligatorio': False, 'orden': 4,
             'formula': 'precio_unitario * cantidad'},
            {'nombre': 'precio_unitario', 'tipo': 'numero',   'obligatorio': False, 'orden': 5},
            {'nombre': 'descuento',       'tipo': 'numero',   'obligatorio': False, 'orden': 6},
            {'nombre': 'total',           'tipo': 'calculado','obligatorio': False, 'orden': 7,
             'formula': 'subtotal - descuento'},
            {'nombre': 'observacion',     'tipo': 'textarea', 'obligatorio': False, 'orden': 8},
        ],
    },
    {
        'nombre': 'MovimientosInventario',
        'descripcion': 'Registro de movimientos de inventario: entradas, salidas y correcciones.',
        'campos': [
            {'nombre': 'producto',        'tipo': 'relacion', 'obligatorio': True,  'orden': 1,
             'formulario_destino_nombre': 'Productos'},
            {'nombre': 'tipo',            'tipo': 'lista',    'obligatorio': True,  'orden': 2,
             'opciones': ['Entrada', 'Salida', 'Correccion']},
            {'nombre': 'cantidad',        'tipo': 'numero',   'obligatorio': True,  'orden': 3},
            {'nombre': 'motivo',          'tipo': 'lista',    'obligatorio': False, 'orden': 4,
             'opciones': [
                 'Compra a proveedor', 'Devolucion de cliente',
                 'Venta del sistema', 'Producto danado',
                 'Perdida', 'Robo', 'Conteo fisico',
                 'Correccion manual', 'Devolucion a proveedor',
             ]},
            {'nombre': 'stock_anterior',  'tipo': 'numero',   'obligatorio': False, 'orden': 5},
            {'nombre': 'stock_nuevo',     'tipo': 'numero',   'obligatorio': False, 'orden': 6},
            {'nombre': 'observacion',     'tipo': 'textarea', 'obligatorio': False, 'orden': 7},
        ],
    },
]


class Command(BaseCommand):
    help = 'Crea los formularios base del sistema: Productos, Clientes, Ventas, MovimientosInventario'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Sembrando formularios base...'))
        self.stdout.write('')

        creados = 0
        actualizados = 0

        for definicion in FORMULARIOS_BASE:
            nombre = definicion['nombre']
            descripcion = definicion['descripcion']

            # Crear o actualizar el formulario
            formulario, es_nuevo = Formulario.objects.get_or_create(
                nombre=nombre,
                defaults={
                    'descripcion': descripcion,
                    'activo': True,
                }
            )

            if es_nuevo:
                self.stdout.write(f'  [OK] Creado formulario: "{nombre}"')
                creados += 1
            else:
                # Actualizar descripción si cambió
                if formulario.descripcion != descripcion:
                    formulario.descripcion = descripcion
                    formulario.save(update_fields=['descripcion'])
                self.stdout.write(f'  [OK] Formulario existente: "{nombre}"')
                actualizados += 1

            # Crear o actualizar campos
            for i, campo_def in enumerate(definicion['campos']):
                nombre_campo = campo_def['nombre']

                # Resolver formulario_destino si aplica
                formulario_destino = None
                if 'formulario_destino_nombre' in campo_def:
                    try:
                        formulario_destino = Formulario.objects.get(
                            nombre=campo_def['formulario_destino_nombre']
                        )
                    except Formulario.DoesNotExist:
                        self.stdout.write(
                            self.style.WARNING(                            f'    [WARN] Formulario destino "{campo_def["formulario_destino_nombre"]}" '
                        f'no encontrado para campo "{nombre_campo}". Se creara sin relacion.'
                            )
                        )

                defaults = {
                    'tipo': campo_def['tipo'],
                    'obligatorio': campo_def.get('obligatorio', False),
                    'orden': campo_def.get('orden', i + 1),
                    'opciones': campo_def.get('opciones'),
                    'unico': campo_def.get('unico', False),
                    'formula': campo_def.get('formula', ''),
                    'formulario_destino': formulario_destino,
                    'activo': True,
                }

                campo_existente = formulario.campos.filter(nombre=nombre_campo).first()
                if campo_existente:
                    # Actualizar campo existente
                    for attr, value in defaults.items():
                        setattr(campo_existente, attr, value)
                    campo_existente.save()
                else:
                    Campo.objects.create(
                        formulario=formulario,
                        nombre=nombre_campo,
                        **defaults,
                    )

            total_campos = formulario.campos.filter(activo=True).count()
            self.stdout.write(f'    -> {total_campos} campos activos')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Proceso completado. Formularios creados: {creados}, actualizados: {actualizados}'
        ))

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_LABEL('Resumen de formularios base:'))
        for f in FORMULARIOS_BASE:
            self.stdout.write(f'    - {f["nombre"]} ({len(f["campos"])} campos)')
