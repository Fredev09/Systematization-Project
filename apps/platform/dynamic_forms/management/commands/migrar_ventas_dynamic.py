"""
Management command para migrar ventas legacy → Dynamic Forms.

Idempotente: puede ejecutarse múltiples veces sin duplicar registros.
Usa un campo `id_legacy` en el formulario Ventas como trazabilidad.

Requisitos:
    - Los productos legacy deben haberse migrado primero (migrar_productos_dynamic).
    - Los clientes legacy deben haberse migrado primero (migrar_clientes_dynamic).

Uso:
    python manage.py migrar_ventas_dynamic
    python manage.py migrar_ventas_dynamic --dry-run
    python manage.py migrar_ventas_dynamic --force
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import models, transaction

from apps.legacy.ventas.models import Venta
from apps.platform.dynamic_forms.models import Campo, Formulario, Registro, ValorCampo
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

logger = logging.getLogger(__name__)

FORM_VENTAS = 'Ventas'
FORM_PRODUCTOS = 'Productos'
FORM_CLIENTES = 'Clientes'
SKU_PREFIX = 'LEGACY-'


def _decimal(valor, default=0):
    try:
        return Decimal(str(valor).strip().replace(',', '.'))
    except (ValueError, TypeError):
        return Decimal(str(default))


def _entero(valor, default=0):
    try:
        return int(str(valor).strip())
    except (ValueError, TypeError):
        return default


class Command(BaseCommand):
    help = 'Migra ventas legacy (modelo Venta) a Dynamic Forms.'

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
        self.dry_run = options['dry_run']
        self.force = options['force']

        self.stdout.write(self.style.MIGRATE_HEADING(
            'Migración de Ventas Legacy → Dynamic Forms'
        ))
        self.stdout.write(f'  Modo: {"DRY RUN (sin escritura)" if self.dry_run else "EJECUCIÓN"}')
        if self.force:
            self.stdout.write('  Force: re-migrará ventas existentes')
        self.stdout.write('')

        if not self._verificar_requisitos():
            self.stdout.write(self.style.ERROR('Migración abortada por requisitos insatisfechos.'))
            return

        self._asegurar_campo_id_legacy()

        stats = self._migrar_ventas()

        validaciones = self._validar_post_migracion()

        self._reportar(stats, validaciones)

    def _verificar_requisitos(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[1/5] Verificando requisitos...'))
        ok = True

        for nombre_form in [FORM_VENTAS, FORM_PRODUCTOS, FORM_CLIENTES]:
            try:
                f = Formulario.objects.get(nombre=nombre_form)
                self.stdout.write(f'  ✓ Formulario "{nombre_form}" existe (id={f.id})')
            except Formulario.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ Formulario "{nombre_form}" NO existe. '
                    'Ejecuta: python manage.py sembrar_formularios_base'
                ))
                ok = False

        if not ok:
            return False

        campos_ventas = ['producto', 'cantidad', 'cliente', 'precio_unitario', 'total',
                         'descuento', 'observacion']
        form_ventas = Formulario.objects.get(nombre=FORM_VENTAS)
        campos_existentes = {c.nombre for c in form_ventas.campos.filter(activo=True)}
        for nombre_campo in campos_ventas:
            if nombre_campo in campos_existentes:
                self.stdout.write(f'  ✓ Campo "{nombre_campo}" existe en Ventas')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ Campo "{nombre_campo}" NO existe en Ventas'
                ))

        # Verificar que productos legacy han sido migrados
        campo_sku = Campo.objects.filter(
            formulario__nombre=FORM_PRODUCTOS, nombre='sku'
        ).first()
        if campo_sku:
            productos_migrados = ValorCampo.objects.filter(
                campo=campo_sku, valor__startswith=SKU_PREFIX
            ).count()
            self.stdout.write(f'  ℹ Productos dinámicos migrados (SKU legacy): {productos_migrados}')
        else:
            self.stdout.write(self.style.WARNING('  ⚠ Campo "sku" no encontrado en Productos'))

        # Verificar que productos legacy existen
        total_productos_legacy = Venta.objects.values('producto').distinct().count()
        self.stdout.write(f'  ℹ Productos distintos en ventas legacy: {total_productos_legacy}')

        total = Venta.objects.count()
        self.stdout.write(f'  ℹ Ventas legacy encontradas: {total}')
        if total == 0:
            self.stdout.write(self.style.WARNING('  ⚠ No hay ventas legacy para migrar.'))
            ok = False

        self.stdout.write('')
        return ok

    def _asegurar_campo_id_legacy(self):
        """Crea el campo `id_legacy` en el formulario Ventas si no existe."""
        self.stdout.write(self.style.MIGRATE_LABEL('[1b/5] Asegurando campo id_legacy...'))
        formulario = Formulario.objects.get(nombre=FORM_VENTAS)
        campo_existente = formulario.campos.filter(nombre='id_legacy').first()
        if campo_existente:
            self.stdout.write('  ✓ Campo "id_legacy" ya existe en Ventas')
            return

        if self.dry_run:
            self.stdout.write('  ⚠ (DRY-RUN) Se crearía campo "id_legacy" en Ventas')
            return

        # Encontrar el orden máximo actual
        max_orden = formulario.campos.aggregate(
            max_orden=models.Max('orden')
        )['max_orden'] or 0

        Campo.objects.create(
            formulario=formulario,
            nombre='id_legacy',
            tipo='texto',
            obligatorio=False,
            orden=max_orden + 1,
            activo=True,
        )
        self.stdout.write(self.style.SUCCESS(
            '  ✓ Campo "id_legacy" creado en formulario Ventas'
        ))
        self.stdout.write('')

    def _buscar_producto_por_sku_legacy(self, producto_id):
        """Busca un Registro dinámico de Producto por su SKU legacy."""
        sku = f'{SKU_PREFIX}{producto_id}'
        try:
            campo_sku = Campo.objects.get(
                formulario__nombre=FORM_PRODUCTOS,
                nombre='sku',
            )
            vc = ValorCampo.objects.get(campo=campo_sku, valor=sku)
            return vc.registro
        except (Campo.DoesNotExist, ValorCampo.DoesNotExist):
            return None

    def _buscar_cliente_por_documento(self, documento):
        """Busca un Registro dinámico de Cliente por su documento."""
        if not documento:
            return None
        try:
            campo_doc = Campo.objects.get(
                formulario__nombre=FORM_CLIENTES,
                nombre='documento',
            )
            vc = ValorCampo.objects.get(campo=campo_doc, valor=documento.strip())
            return vc.registro
        except (Campo.DoesNotExist, ValorCampo.DoesNotExist):
            return None

    def _buscar_venta_por_id_legacy(self, id_legacy):
        """Busca un Registro dinámico de Venta por su id_legacy."""
        try:
            campo_id = Campo.objects.get(
                formulario__nombre=FORM_VENTAS,
                nombre='id_legacy',
            )
            vc = ValorCampo.objects.get(campo=campo_id, valor=str(id_legacy))
            return vc.registro
        except (Campo.DoesNotExist, ValorCampo.DoesNotExist):
            return None

    def _migrar_ventas(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[2/5] Migrando ventas...'))
        stats = {
            'total_legacy': 0,
            'creados': 0,
            'actualizados': 0,
            'omitidos': 0,
            'errores': [],
            'sin_producto_dinamico': 0,
            'con_descuento_redondeo': 0,
        }

        ventas = Venta.objects.select_related('producto', 'cliente', 'vendedor').order_by('id')
        stats['total_legacy'] = ventas.count()
        self.stdout.write(f'  Ventas a procesar: {stats["total_legacy"]}')
        self.stdout.write('')

        for i, venta in enumerate(ventas, 1):
            self.stdout.write(f'  [{i}/{stats["total_legacy"]}] Venta #{venta.id}... ', ending='')
            try:
                self._migrar_una_venta(venta, stats)
            except Exception as e:
                stats['errores'].append((venta.id, str(e)))
                self.stdout.write(self.style.ERROR(f'ERROR: {e}'))
                logger.exception(f'Error migrando venta #{venta.id}')

        self.stdout.write('')
        return stats

    def _migrar_una_venta(self, venta, stats):
        if self._buscar_venta_por_id_legacy(venta.id) and not self.force:
            stats['omitidos'] += 1
            self.stdout.write('omitido (ya migrado) ')
            return

        # Resolver producto dinámico
        registro_producto = self._buscar_producto_por_sku_legacy(venta.producto_id)
        if not registro_producto:
            stats['sin_producto_dinamico'] += 1
            self.stdout.write(self.style.WARNING(
                f'omitido (producto #{venta.producto_id} no migrado) '
            ))
            return

        # Resolver cliente dinámico (si existe)
        registro_cliente = None
        if venta.cliente_id:
            registro_cliente = self._buscar_cliente_por_documento(venta.cliente.documento)

        # Calcular precio_unitario y descuento para preservar el total exacto
        cantidad = _entero(venta.cantidad, 1)
        total = _decimal(venta.total if venta.total is not None else 0)

        if cantidad <= 0:
            stats['omitidos'] += 1
            self.stdout.write(self.style.WARNING('omitido (cantidad inválida) '))
            return

        # Calcular precio_unitario para que precio_unitario * cantidad = total
        precio_unitario = (total / Decimal(str(cantidad))).quantize(
            Decimal('0.0001'), rounding=ROUND_HALF_UP
        )

        valores_dict = {
            'producto': str(registro_producto.id),
            'cantidad': str(cantidad),
            'precio_unitario': str(precio_unitario),
            'descuento': '0',
            'observacion': (
                f'Venta #{venta.id} migrada del sistema legacy.'
                if venta.cliente_id
                else f'Venta #{venta.id} migrada del sistema legacy.'
            ),
            'id_legacy': str(venta.id),
        }

        if registro_cliente:
            valores_dict['cliente'] = str(registro_cliente.id)

        if self.dry_run:
            self.stdout.write('[CREARÍA] ', ending='')
            stats['creados'] += 1
            return

        # Deshabilitar hook post_crear temporalmente para no decrementar stock otra vez
        formulario_ventas = Formulario.objects.get(nombre=FORM_VENTAS)
        hook_original = formulario_ventas.hook_post_crear
        if hook_original:
            formulario_ventas.hook_post_crear = None
            formulario_ventas.save(update_fields=['hook_post_crear'])

        try:
            with transaction.atomic():
                registro = DS.crear(
                    FORM_VENTAS,
                    valores_dict,
                    usuario=venta.vendedor,
                )
                # Preservar fecha original
                Registro.objects.filter(id=registro.id).update(
                    fecha_creacion=venta.fecha
                )

            stats['creados'] += 1
            self.stdout.write(self.style.SUCCESS(f'creado (id={registro.id}) '), ending='')

            # Verificar que el total calculado coincida
            total_calculado = DS.obtener_valor(registro, 'total', '0')
            if _decimal(total_calculado) != total:
                stats['con_descuento_redondeo'] += 1
                diff = total - _decimal(total_calculado)
                self.stdout.write(
                    self.style.WARNING(f'[diff total: {diff}] '), ending=''
                )

        except Exception as e:
            raise Exception(f'Error creando venta: {e}') from e
        finally:
            if hook_original:
                formulario_ventas.hook_post_crear = hook_original
                formulario_ventas.save(update_fields=['hook_post_crear'])

        self.stdout.write('')

    def _validar_post_migracion(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[4/5] Validando post-migración...'))

        if self.dry_run:
            self.stdout.write('  (omitido en dry-run)')
            self.stdout.write('')
            return {}

        validaciones = {}

        total_legacy = Venta.objects.count()

        campo_id_legacy = Campo.objects.filter(
            formulario__nombre=FORM_VENTAS, nombre='id_legacy'
        ).first()
        if campo_id_legacy:
            vcs = ValorCampo.objects.filter(campo=campo_id_legacy)
            ids_migrados = {vc.valor for vc in vcs}
            total_migrados = len(ids_migrados)
            validaciones['total_migrados'] = total_migrados
            self.stdout.write(f'  ✓ Ventas migradas exitosamente: {total_migrados}')

            legacy_ids = set(str(i) for i in Venta.objects.values_list('id', flat=True))
            no_migrados = legacy_ids - ids_migrados
            if no_migrados:
                validaciones['ventas_no_migradas'] = sorted(
                    int(x) for x in no_migrados if x.isdigit()
                )
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ Ventas legacy sin migrar ({len(no_migrados)}): {sorted(no_migrados)[:20]}'
                ))

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
        else:
            self.stdout.write(self.style.WARNING('  ⚠ Campo "id_legacy" no encontrado'))
            validaciones['error_id_legacy'] = True

        self.stdout.write('')
        return validaciones

    def _reportar(self, stats, validaciones):
        self.stdout.write(self.style.MIGRATE_LABEL('[5/5] Resumen final'))
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 55))
        self.stdout.write(self.style.MIGRATE_HEADING('  RESUMEN DE MIGRACIÓN — VENTAS'))
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 55))
        self.stdout.write('')

        self.stdout.write('  Ventas:')
        self.stdout.write(f'    Legacy encontradas:        {stats["total_legacy"]}')
        self.stdout.write(f'    Creadas:                   {stats["creados"]}')
        self.stdout.write(f'    Actualizadas:              {stats["actualizados"]}')
        self.stdout.write(f'    Omitidas (ya migradas):    {stats["omitidos"]}')
        self.stdout.write(f'    Sin producto dinámico:     {stats["sin_producto_dinamico"]}')
        self.stdout.write(f'    Con diff por redondeo:     {stats["con_descuento_redondeo"]}')
        self.stdout.write(f'    Errores:                   {len(stats["errores"])}')
        self.stdout.write('')

        if stats['errores']:
            self.stdout.write(self.style.ERROR('  Errores:'))
            for venta_id, error in stats['errores']:
                self.stdout.write(f'    #{venta_id}: {error}')
            self.stdout.write('')

        if validaciones:
            self.stdout.write('  Validaciones:')
            if 'total_migrados' in validaciones:
                pct = validaciones['total_migrados'] * 100 // max(stats['total_legacy'], 1)
                self.stdout.write(f'    Cobertura:                 {pct}%')
            if 'ventas_no_migradas' in validaciones:
                self.stdout.write(self.style.WARNING(
                    f'    Ventas no migradas:        {len(validaciones["ventas_no_migradas"])}'
                ))
            self.stdout.write('')

        errores = len(stats['errores'])
        if errores == 0 and (stats['creados'] > 0 or stats['omitidos'] > 0):
            total_procesadas = stats['creados'] + stats['omitidos']
            if total_procesadas >= stats['total_legacy']:
                self.stdout.write(self.style.SUCCESS('  ✅ Migración completada exitosamente'))
            else:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ Parcial: {total_procesadas}/{stats["total_legacy"]} procesadas'
                ))
        elif errores == 0 and stats['creados'] == 0 and stats['omitidos'] == 0:
            self.stdout.write(self.style.WARNING('  ⚠ No se realizaron cambios'))
        else:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Migración completada con {errores} error(es)'
            ))
        self.stdout.write('')
