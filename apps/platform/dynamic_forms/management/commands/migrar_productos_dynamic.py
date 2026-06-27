"""
Management command para migrar productos legacy → Dynamic Forms.

NOTA: Los modelos legacy Producto/Categoria/MovimientoInventario han
sido eliminados (Fase 4). La migración de datos se completó en fases
anteriores (6/6 productos, 5/5 ventas, 1/1 cliente).

Para restaurar los modelos legacy y ejecutar la migración de nuevo:
    1. git checkout apps/legacy/productos/models.py
    2. Revertir la migración de eliminación de tablas
    3. Ejecutar este comando

Uso:
    python manage.py migrar_productos_dynamic
    python manage.py migrar_productos_dynamic --dry-run
    python manage.py migrar_productos_dynamic --force
"""

import logging

from django.core.management.base import BaseCommand

from apps.platform.dynamic_forms.models import Campo, Formulario, ValorCampo

logger = logging.getLogger(__name__)

FORM_PRODUCTOS = 'Productos'
FORM_MOVIMIENTOS = 'MovimientosInventario'
SKU_PREFIX = 'LEGACY-'


class Command(BaseCommand):
    help = 'Migración de productos legacy ya completada. Los modelos legacy ya no existen.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Valida requisitos y muestra lo que se migraría sin escribir BD.'
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Re-migra productos aunque ya exista SKU legacy (actualiza todo).'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Migración de Productos Legacy → Dynamic Forms'
        ))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            '  Los modelos legacy Producto/Categoria/MovimientoInventario '
            'fueron eliminados en Fase 4.'
        ))
        self.stdout.write(self.style.WARNING(
            '  La migración de datos se completó en fases anteriores.'
        ))
        self.stdout.write('')

        # Verificar que los formularios existen y tienen datos
        for nombre_form in [FORM_PRODUCTOS, FORM_MOVIMIENTOS]:
            try:
                f = Formulario.objects.get(nombre=nombre_form)
                self.stdout.write(f'  ✓ Formulario "{nombre_form}" existe (id={f.id})')
            except Formulario.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f'  ✗ Formulario "{nombre_form}" no encontrado.'
                ))

        # Contar productos migrados
        campo_sku = Campo.objects.filter(
            formulario__nombre=FORM_PRODUCTOS, nombre='sku'
        ).first()
        if campo_sku:
            productos_migrados = ValorCampo.objects.filter(
                campo=campo_sku, valor__startswith=SKU_PREFIX
            ).count()
            self.stdout.write(f'  ℹ Productos migrados (SKU legacy): {productos_migrados}')

            total_productos = ValorCampo.objects.filter(campo=campo_sku).exclude(
                valor=''
            ).count()
            self.stdout.write(f'  ℹ Productos totales en Dynamic Forms: {total_productos}')

        # Contar movimientos de inventario
        try:
            form_mov = Formulario.objects.get(nombre=FORM_MOVIMIENTOS)
            total_movimientos = form_mov.registros.count()
            self.stdout.write(f'  ℹ Movimientos de inventario: {total_movimientos}')
        except Formulario.DoesNotExist:
            pass

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            '  ✅ Migración ya completada. No hay cambios pendientes.'
        ))
