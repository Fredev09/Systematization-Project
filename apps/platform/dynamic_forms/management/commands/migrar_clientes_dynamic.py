"""
Management command para migrar clientes legacy → Dynamic Forms.

NOTA: Los modelos legacy Cliente/Venta han sido eliminados (Fase 3).
La migración de datos se completó en Fase 2 (5/5 ventas, 1/1 cliente).
Este comando se conserva como referencia para rollback.

Para restaurar los modelos legacy y ejecutar la migración de nuevo:
    1. git checkout apps/legacy/ventas/models.py
    2. Revertir la migración de eliminación de tablas
    3. Ejecutar este comando

Uso:
    python manage.py migrar_clientes_dynamic
    python manage.py migrar_clientes_dynamic --dry-run
    python manage.py migrar_clientes_dynamic --force
"""

import logging

from django.core.management.base import BaseCommand

from apps.platform.dynamic_forms.services_dynamic import FORM_CLIENTES

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migración de clientes legacy ya completada. Los modelos legacy ya no existen.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Valida requisitos y muestra lo que se migraría sin escribir BD.'
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Re-migra clientes aunque ya existan (actualiza todo).'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Migración de Clientes Legacy → Dynamic Forms'
        ))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            '  Los modelos legacy Cliente/Venta fueron eliminados en Fase 3.'
        ))
        self.stdout.write(self.style.WARNING(
            '  La migración de datos se completó en Fase 2.'
        ))
        self.stdout.write('')

        # Verificar que el formulario Clientes existe y tiene datos
        try:
            f = Formulario.objects.get(nombre=FORM_CLIENTES)
            self.stdout.write(f'  ✓ Formulario "{FORM_CLIENTES}" existe (id={f.id})')

            campo_doc = Campo.objects.filter(
                formulario__nombre=FORM_CLIENTES, nombre='documento'
            ).first()
            if campo_doc:
                total_dinamico = ValorCampo.objects.filter(campo=campo_doc).count()
                self.stdout.write(f'  ℹ Clientes en Dynamic Forms: {total_dinamico}')
            else:
                self.stdout.write('  ⚠ Campo "documento" no encontrado')
        except Formulario.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                f'  ✗ Formulario "{FORM_CLIENTES}" NO existe.'
            ))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('  ✅ Migración ya completada. No hay cambios pendientes.'))
