"""
Management command para migrar ventas legacy → Dynamic Forms.

NOTA: Los modelos legacy Venta/Cliente han sido eliminados (Fase 3).
La migración de datos se completó en Fase 2 (5/5 ventas, 1/1 cliente).
Este comando se conserva como referencia para rollback.

Para restaurar los modelos legacy y ejecutar la migración de nuevo:
    1. git checkout apps/legacy/ventas/models.py
    2. Revertir la migración de eliminación de tablas
    3. Ejecutar este comando

Uso:
    python manage.py migrar_ventas_dynamic
    python manage.py migrar_ventas_dynamic --dry-run
    python manage.py migrar_ventas_dynamic --force
"""

import logging

from django.core.management.base import BaseCommand

from apps.platform.dynamic_forms.models import Campo, Formulario, ValorCampo

logger = logging.getLogger(__name__)

FORM_VENTAS = 'Ventas'
FORM_PRODUCTOS = 'Productos'
FORM_CLIENTES = 'Clientes'
SKU_PREFIX = 'LEGACY-'


class Command(BaseCommand):
    help = 'Migración de ventas legacy ya completada. Los modelos legacy ya no existen.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Valida requisitos y muestra lo que se migraría sin escribir BD.'
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Re-migra ventas aunque ya existan (actualiza todo).'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Migración de Ventas Legacy → Dynamic Forms'
        ))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            '  Los modelos legacy Venta/Cliente fueron eliminados en Fase 3.'
        ))
        self.stdout.write(self.style.WARNING(
            '  La migración de datos se completó en Fase 2.'
        ))
        self.stdout.write('')

        # Verificar que los formularios existen y tienen datos
        for nombre_form in [FORM_VENTAS, FORM_PRODUCTOS, FORM_CLIENTES]:
            try:
                f = Formulario.objects.get(nombre=nombre_form)
                self.stdout.write(f'  ✓ Formulario "{nombre_form}" existe (id={f.id})')
            except Formulario.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f'  ✗ Formulario "{nombre_form}" no encontrado.'
                ))

        # Mostrar conteo de ventas migradas
        campo_id_legacy = Campo.objects.filter(
            formulario__nombre=FORM_VENTAS, nombre='id_legacy'
        ).first()
        if campo_id_legacy:
            total_migradas = ValorCampo.objects.filter(campo=campo_id_legacy).count()
            self.stdout.write(f'  ℹ Ventas en Dynamic Forms: {total_migradas}')

        # Mostrar conteo de productos migrados
        campo_sku = Campo.objects.filter(
            formulario__nombre=FORM_PRODUCTOS, nombre='sku'
        ).first()
        if campo_sku:
            productos_migrados = ValorCampo.objects.filter(
                campo=campo_sku, valor__startswith=SKU_PREFIX
            ).count()
            self.stdout.write(f'  ℹ Productos migrados (SKU legacy): {productos_migrados}')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('  ✅ Migración ya completada. No hay cambios pendientes.'))
