"""
Management command para verificar la integridad de los datos en Dynamic Forms.

NOTA: Los modelos legacy (Venta, Cliente, Producto) fueron eliminados en Fase 3.
Este comando ahora solo verifica la integridad de los datos dinámicos:
    - Conteo de registros en Dynamic Forms
    - Relaciones rotas (producto/cliente en ventas que no existen)
    - Duplicados

Uso:
    python manage.py verificar_integridad_dynamic
"""

import logging
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import models

from apps.platform.dynamic_forms.models import Campo, Formulario, Registro, ValorCampo
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

logger = logging.getLogger(__name__)

FORM_PRODUCTOS = 'Productos'
FORM_VENTAS = 'Ventas'
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
    help = 'Verifica la integridad de los datos en Dynamic Forms.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Verificación de Integridad — Dynamic Forms'
        ))
        self.stdout.write('')

        self._verificar_productos()
        self._verificar_clientes()
        self._verificar_ventas()
        self._verificar_relaciones_rotas()
        self._verificar_duplicados()

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 55))
        self.stdout.write('')
        self.stdout.write('  La verificación de integridad ha finalizado.')
        self.stdout.write('')

    # ==================================================================
    # PRODUCTOS
    # ==================================================================

    def _verificar_productos(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[1] Verificando productos...'))

        try:
            form_productos = Formulario.objects.get(nombre=FORM_PRODUCTOS)
            total_productos = Registro.objects.filter(formulario=form_productos).count()
            self.stdout.write(f'  Productos en Dynamic Forms: {total_productos}')

            campo_sku = Campo.objects.get(formulario__nombre=FORM_PRODUCTOS, nombre='sku')
            legacy_sku_count = ValorCampo.objects.filter(
                campo=campo_sku, valor__startswith=SKU_PREFIX
            ).count()
            self.stdout.write(f'  Productos migrados (SKU legacy): {legacy_sku_count}')

            if total_productos > 0:
                self.stdout.write(self.style.SUCCESS('    ✓ Datos de productos presentes'))
        except (Formulario.DoesNotExist, Campo.DoesNotExist) as e:
            self.stdout.write(self.style.WARNING(f'    ⚠ {e}'))

        self.stdout.write('')

    # ==================================================================
    # CLIENTES
    # ==================================================================

    def _verificar_clientes(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[2] Verificando clientes...'))

        try:
            form_clientes = Formulario.objects.get(nombre=FORM_CLIENTES)
            total_clientes = Registro.objects.filter(formulario=form_clientes).count()
            self.stdout.write(f'  Clientes en Dynamic Forms: {total_clientes}')

            if total_clientes > 0:
                # Mostrar algunos clientes de muestra
                campo_doc = Campo.objects.get(formulario=form_clientes, nombre='documento')
                docs = ValorCampo.objects.filter(campo=campo_doc).values_list('valor', flat=True)[:5]
                if docs:
                    self.stdout.write(f'  Documentos (muestra): {", ".join(docs)}')

            if total_clientes > 0:
                self.stdout.write(self.style.SUCCESS('    ✓ Datos de clientes presentes'))
        except (Formulario.DoesNotExist, Campo.DoesNotExist) as e:
            self.stdout.write(self.style.WARNING(f'    ⚠ {e}'))

        self.stdout.write('')

    # ==================================================================
    # VENTAS
    # ==================================================================

    def _verificar_ventas(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[3] Verificando ventas...'))

        try:
            form_ventas = Formulario.objects.get(nombre=FORM_VENTAS)
            total_ventas = Registro.objects.filter(formulario=form_ventas).count()
            self.stdout.write(f'  Ventas en Dynamic Forms:    {total_ventas}')

            campo_id_legacy = Campo.objects.filter(
                formulario=form_ventas, nombre='id_legacy'
            ).first()
            if campo_id_legacy:
                migradas = ValorCampo.objects.filter(campo=campo_id_legacy).count()
                self.stdout.write(f'  Ventas con id_legacy:       {migradas}')

            # Sumar totales monetarios
            campo_total = Campo.objects.filter(
                formulario=form_ventas, nombre='total'
            ).first()
            if campo_total:
                total_dinamico = Decimal('0')
                for vc in ValorCampo.objects.filter(campo=campo_total):
                    total_dinamico += _decimal(vc.valor, 0)
                self.stdout.write(f'  Total monetario:            ${total_dinamico:,.2f}')

            # Verificar vendedores asignados
            ventas_sin_usuario = Registro.objects.filter(
                formulario=form_ventas, usuario__isnull=True
            ).count()
            if ventas_sin_usuario > 0:
                self.stdout.write(self.style.WARNING(
                    f'    ⚠ {ventas_sin_usuario} venta(s) sin vendedor asignado'
                ))

            if total_ventas > 0:
                self.stdout.write(self.style.SUCCESS('    ✓ Datos de ventas presentes'))

                # Calcular total de cantidades vendidas
                campo_cant = Campo.objects.filter(
                    formulario=form_ventas, nombre='cantidad'
                ).first()
                if campo_cant:
                    total_cant = sum(
                        _entero(vc.valor, 0)
                        for vc in ValorCampo.objects.filter(campo=campo_cant)
                    )
                    self.stdout.write(f'  Unidades vendidas:          {total_cant}')

        except Formulario.DoesNotExist as e:
            self.stdout.write(self.style.WARNING(f'    ⚠ {e}'))

        self.stdout.write('')

    # ==================================================================
    # RELACIONES ROTAS
    # ==================================================================

    def _verificar_relaciones_rotas(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[4] Verificando relaciones rotas...'))

        try:
            formulario = Formulario.objects.get(nombre=FORM_VENTAS)
            campo_producto = formulario.campos.filter(nombre='producto').first()

            if not campo_producto:
                self.stdout.write(self.style.WARNING('    ⚠ Campo "producto" no encontrado en Ventas'))
                self.stdout.write('')
                return

            # Productos rotos
            vcs_producto = ValorCampo.objects.filter(campo=campo_producto).select_related('registro')
            productos_rotos = 0

            for vc in vcs_producto:
                prod_id = vc.valor.strip()
                if prod_id and prod_id.isdigit():
                    exists = Registro.objects.filter(
                        id=int(prod_id), formulario__nombre=FORM_PRODUCTOS
                    ).exists()
                    if not exists:
                        productos_rotos += 1
                        self.stdout.write(self.style.WARNING(
                            f'    ⚠ Venta #{vc.registro_id}: producto #{prod_id} no existe'
                        ))

            if productos_rotos == 0:
                self.stdout.write(self.style.SUCCESS('    ✓ 0 relaciones rotas a Productos'))
            else:
                self.stdout.write(self.style.ERROR(
                    f'    ✗ {productos_rotos} relación(es) rota(s) a Productos'
                ))

            # Clientes rotos
            campo_cliente = formulario.campos.filter(nombre='cliente').first()
            clientes_rotos = 0
            if campo_cliente:
                vcs_cliente = ValorCampo.objects.filter(campo=campo_cliente).select_related('registro')
                for vc in vcs_cliente:
                    cli_id = vc.valor.strip()
                    if cli_id and cli_id.isdigit():
                        exists = Registro.objects.filter(
                            id=int(cli_id), formulario__nombre=FORM_CLIENTES
                        ).exists()
                        if not exists:
                            clientes_rotos += 1
                            self.stdout.write(self.style.WARNING(
                                f'    ⚠ Venta #{vc.registro_id}: cliente #{cli_id} no existe'
                            ))

            if clientes_rotos == 0:
                self.stdout.write(self.style.SUCCESS('    ✓ 0 relaciones rotas a Clientes'))
            else:
                self.stdout.write(self.style.ERROR(
                    f'    ✗ {clientes_rotos} relación(es) rota(s) a Clientes'
                ))

        except Formulario.DoesNotExist:
            self.stdout.write(self.style.WARNING('    ⚠ Formulario Ventas no existe'))

        self.stdout.write('')

    # ==================================================================
    # DUPLICADOS
    # ==================================================================

    def _verificar_duplicados(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[5] Verificando duplicados...'))

        # Duplicados en documentos de Clientes
        try:
            campo_doc = Campo.objects.get(formulario__nombre=FORM_CLIENTES, nombre='documento')
            vcs = ValorCampo.objects.filter(campo=campo_doc).values('valor').annotate(
                cnt=models.Count('id')
            ).filter(cnt__gt=1)
            duplicados = list(vcs)
            if duplicados:
                self.stdout.write(self.style.ERROR(
                    f'    ✗ {len(duplicados)} documento(s) duplicado(s) en Clientes'
                ))
                for d in duplicados:
                    self.stdout.write(f'      - Documento: "{d["valor"]}" ({d["cnt"]} veces)')
            else:
                self.stdout.write(self.style.SUCCESS('    ✓ 0 documentos duplicados en Clientes'))
        except Campo.DoesNotExist:
            self.stdout.write(self.style.WARNING('    ⚠ No se puede verificar (campo documento no existe)'))

        # Duplicados en id_legacy de Ventas
        try:
            campo_id = Campo.objects.get(formulario__nombre=FORM_VENTAS, nombre='id_legacy')
            vcs_id = ValorCampo.objects.filter(campo=campo_id).values('valor').annotate(
                cnt=models.Count('id')
            ).filter(cnt__gt=1)
            duplicados_id = list(vcs_id)
            if duplicados_id:
                self.stdout.write(self.style.ERROR(
                    f'    ✗ {len(duplicados_id)} id_legacy duplicado(s) en Ventas'
                ))
                for d in duplicados_id:
                    self.stdout.write(f'      - id_legacy: "{d["valor"]}" ({d["cnt"]} veces)')
            else:
                self.stdout.write(self.style.SUCCESS('    ✓ 0 id_legacy duplicados en Ventas'))
        except Campo.DoesNotExist:
            self.stdout.write(self.style.WARNING('    ⚠ No se puede verificar (campo id_legacy no existe)'))

        # Duplicados en SKU de Productos
        try:
            campo_sku = Campo.objects.get(formulario__nombre=FORM_PRODUCTOS, nombre='sku')
            vcs_sku = ValorCampo.objects.filter(campo=campo_sku).exclude(valor='').values('valor').annotate(
                cnt=models.Count('id')
            ).filter(cnt__gt=1)
            duplicados_sku = list(vcs_sku)
            if duplicados_sku:
                self.stdout.write(self.style.ERROR(
                    f'    ✗ {len(duplicados_sku)} SKU(s) duplicado(s) en Productos'
                ))
                for d in duplicados_sku:
                    self.stdout.write(f'      - SKU: "{d["valor"]}" ({d["cnt"]} veces)')
            else:
                self.stdout.write(self.style.SUCCESS('    ✓ 0 SKUs duplicados en Productos'))
        except Campo.DoesNotExist:
            self.stdout.write(self.style.WARNING('    ⚠ No se puede verificar (campo sku no existe)'))

        self.stdout.write('')
