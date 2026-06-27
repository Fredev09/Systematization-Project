"""
Management command para migrar clientes legacy → Dynamic Forms.

Idempotente: puede ejecutarse múltiples veces sin duplicar registros.
Usa el campo `documento` (único en ambos sistemas) como trazabilidad.

Uso:
    python manage.py migrar_clientes_dynamic
    python manage.py migrar_clientes_dynamic --dry-run
    python manage.py migrar_clientes_dynamic --force
"""

import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.legacy.ventas.models import Cliente
from apps.platform.dynamic_forms.models import Campo, Formulario, Registro, ValorCampo
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

logger = logging.getLogger(__name__)

FORM_CLIENTES = 'Clientes'


def _booleano(valor, default='No'):
    if valor is True or str(valor).lower() in ('true', '1', 'sí', 'si'):
        return 'Sí'
    return 'No'


class Command(BaseCommand):
    help = 'Migra clientes legacy (modelo Cliente) a Dynamic Forms.'

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
        self.dry_run = options['dry_run']
        self.force = options['force']

        self.stdout.write(self.style.MIGRATE_HEADING(
            'Migración de Clientes Legacy → Dynamic Forms'
        ))
        self.stdout.write(f'  Modo: {"DRY RUN (sin escritura)" if self.dry_run else "EJECUCIÓN"}')
        if self.force:
            self.stdout.write('  Force: re-migrará clientes existentes')
        self.stdout.write('')

        if not self._verificar_requisitos():
            self.stdout.write(self.style.ERROR('Migración abortada por requisitos insatisfechos.'))
            return

        stats = self._migrar_clientes()

        validaciones = self._validar_post_migracion()

        self._reportar(stats, validaciones)

    def _verificar_requisitos(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[1/4] Verificando requisitos...'))
        ok = True

        try:
            f = Formulario.objects.get(nombre=FORM_CLIENTES)
            self.stdout.write(f'  ✓ Formulario "{FORM_CLIENTES}" existe (id={f.id})')
        except Formulario.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                f'  ✗ Formulario "{FORM_CLIENTES}" NO existe. '
                'Ejecuta: python manage.py sembrar_formularios_base'
            ))
            ok = False

        if not ok:
            return False

        campos_requeridos = ['documento', 'nombre', 'apellido', 'correo', 'telefono', 'activo']
        formulario = Formulario.objects.get(nombre=FORM_CLIENTES)
        campos_existentes = {c.nombre for c in formulario.campos.filter(activo=True)}
        for nombre_campo in campos_requeridos:
            if nombre_campo in campos_existentes:
                self.stdout.write(f'  ✓ Campo "{nombre_campo}" existe en Clientes')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ Campo "{nombre_campo}" NO existe en Clientes'
                ))

        total = Cliente.objects.count()
        self.stdout.write(f'  ℹ Clientes legacy encontrados: {total}')
        if total == 0:
            self.stdout.write(self.style.WARNING('  ⚠ No hay clientes legacy para migrar.'))
            ok = False

        self.stdout.write('')
        return ok

    def _buscar_cliente_por_documento(self, documento):
        """Busca un Registro dinámico de Cliente por su documento (único)."""
        try:
            campo_doc = Campo.objects.get(
                formulario__nombre=FORM_CLIENTES,
                nombre='documento',
            )
            vc = ValorCampo.objects.get(campo=campo_doc, valor=documento.strip())
            return vc.registro
        except (Campo.DoesNotExist, ValorCampo.DoesNotExist):
            return None

    def _migrar_clientes(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[2/4] Migrando clientes...'))
        stats = {
            'total_legacy': 0,
            'creados': 0,
            'actualizados': 0,
            'omitidos': 0,
            'errores': [],
        }

        clientes = Cliente.objects.order_by('id')
        stats['total_legacy'] = clientes.count()
        self.stdout.write(f'  Clientes a procesar: {stats["total_legacy"]}')
        self.stdout.write('')

        for i, cliente in enumerate(clientes, 1):
            self.stdout.write(f'  [{i}/{stats["total_legacy"]}] {cliente.nombre_completo}... ', ending='')
            try:
                self._migrar_un_cliente(cliente, stats)
            except Exception as e:
                stats['errores'].append((cliente.id, cliente.nombre_completo, str(e)))
                self.stdout.write(self.style.ERROR(f'ERROR: {e}'))
                logger.exception(f'Error migrando cliente #{cliente.id} "{cliente.nombre_completo}"')

        self.stdout.write('')
        return stats

    def _migrar_un_cliente(self, cliente, stats):
        documento = (cliente.documento or '').strip()
        if not documento:
            stats['omitidos'] += 1
            self.stdout.write(self.style.WARNING('omitido (sin documento) '))
            return

        registro_existente = self._buscar_cliente_por_documento(documento)

        valores_dict = {
            'documento': documento,
            'nombre': (cliente.nombre or '').strip(),
            'apellido': (cliente.apellido or '').strip(),
            'correo': (cliente.correo or '').strip(),
            'telefono': (cliente.telefono or '').strip(),
            'activo': _booleano(cliente.activo),
        }

        if registro_existente and not self.force:
            if self.dry_run:
                self.stdout.write('[ACTUALIZARÍA] ', ending='')
                stats['actualizados'] += 1
            else:
                DS.actualizar(registro_existente, valores_dict)
                self.stdout.write(self.style.SUCCESS(f'actualizado (id={registro_existente.id}) '), ending='')
                stats['actualizados'] += 1
        else:
            if registro_existente and self.force:
                if not self.dry_run:
                    DS.eliminar(registro_existente)
                    self.stdout.write('[force: eliminado] ', ending='')

            if self.dry_run:
                self.stdout.write('[CREARÍA] ', ending='')
                stats['creados'] += 1
            else:
                with transaction.atomic():
                    registro = DS.crear(FORM_CLIENTES, valores_dict)
                    Registro.objects.filter(id=registro.id).update(
                        fecha_creacion=cliente.fecha_registro
                    )
                self.stdout.write(self.style.SUCCESS(f'creado (id={registro.id}) '), ending='')
                stats['creados'] += 1

        self.stdout.write('')

    def _validar_post_migracion(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[3/4] Validando post-migración...'))

        if self.dry_run:
            self.stdout.write('  (omitido en dry-run)')
            self.stdout.write('')
            return {}

        validaciones = {}

        total_legacy = Cliente.objects.count()

        campo_doc = Campo.objects.get(formulario__nombre=FORM_CLIENTES, nombre='documento')
        vcs = ValorCampo.objects.filter(campo=campo_doc)
        documentos_migrados = {vc.valor for vc in vcs}

        legacy_documentos = set(Cliente.objects.values_list('documento', flat=True))
        no_migrados = legacy_documentos - documentos_migrados
        if no_migrados:
            validaciones['clientes_no_migrados'] = sorted(no_migrados)
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Clientes legacy sin migrar ({len(no_migrados)}): {list(no_migrados)[:20]}'
            ))

        total_migrados = len(documentos_migrados)
        validaciones['total_migrados'] = total_migrados
        self.stdout.write(f'  ✓ Clientes migrados exitosamente: {total_migrados}')

        if total_migrados >= total_legacy:
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ Cobertura: {total_migrados}/{total_legacy} (100%)'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Cobertura: {total_migrados}/{total_legacy} '
                f'({total_migrados * 100 // max(total_legacy, 1)}%)'
            ))
            validaciones['cobertura_parcial'] = True

        self.stdout.write('')
        return validaciones

    def _reportar(self, stats, validaciones):
        self.stdout.write(self.style.MIGRATE_LABEL('[4/4] Resumen final'))
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 55))
        self.stdout.write(self.style.MIGRATE_HEADING('  RESUMEN DE MIGRACIÓN — CLIENTES'))
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 55))
        self.stdout.write('')

        self.stdout.write('  Clientes:')
        self.stdout.write(f'    Legacy encontrados:     {stats["total_legacy"]}')
        self.stdout.write(f'    Creados:                {stats["creados"]}')
        self.stdout.write(f'    Actualizados:           {stats["actualizados"]}')
        self.stdout.write(f'    Omitidos:               {stats["omitidos"]}')
        self.stdout.write(f'    Errores:                {len(stats["errores"])}')
        self.stdout.write('')

        if stats['errores']:
            self.stdout.write(self.style.ERROR('  Errores:'))
            for cli_id, nombre, error in stats['errores']:
                self.stdout.write(f'    #{cli_id} "{nombre}": {error}')
            self.stdout.write('')

        if validaciones:
            self.stdout.write('  Validaciones:')
            if 'total_migrados' in validaciones:
                pct = validaciones['total_migrados'] * 100 // max(stats['total_legacy'], 1)
                self.stdout.write(f'    Cobertura:              {pct}%')
            if 'clientes_no_migrados' in validaciones:
                self.stdout.write(self.style.WARNING(
                    f'    Clientes no migrados:   {len(validaciones["clientes_no_migrados"])}'
                ))
            self.stdout.write('')

        errores = len(stats['errores'])
        if errores == 0 and (stats['creados'] > 0 or stats['actualizados'] > 0):
            self.stdout.write(self.style.SUCCESS('  ✅ Migración completada exitosamente'))
        elif errores == 0 and stats['creados'] == 0 and stats['actualizados'] == 0:
            self.stdout.write(self.style.WARNING('  ⚠ No se realizaron cambios'))
        else:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Migración completada con {errores} error(es)'
            ))
        self.stdout.write('')
