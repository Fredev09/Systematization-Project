"""
Management command para verificar la integridad de los datos migrados.

Compara los datos legacy con los datos en Dynamic Forms para identificar:
    - Diferencias en cantidad de registros
    - Diferencias en totales monetarios
    - Diferencias en cantidades vendidas
    - Registros huérfanos (relaciones rotas)
    - Duplicados

Uso:
    python manage.py verificar_integridad_dynamic
"""

import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import models
from django.db.models import Sum

from apps.legacy.productos.models import Producto as ProductoLegacy
from apps.legacy.ventas.models import Cliente as ClienteLegacy
from apps.legacy.ventas.models import Venta as VentaLegacy
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


class Command(BaseCommand):
    help = 'Verifica la integridad de los datos migrados a Dynamic Forms.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Verificación de Integridad — Datos Migrados'
        ))
        self.stdout.write('')

        self._verificar_productos()
        self._verificar_clientes()
        self._verificar_ventas()
        self._verificar_usuarios_ventas()
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

        count_legacy = ProductoLegacy.objects.count()
        self.stdout.write(f'  Productos legacy:           {count_legacy}')

        # Contar productos dinámicos con SKU legacy
        try:
            campo_sku = Campo.objects.get(formulario__nombre=FORM_PRODUCTOS, nombre='sku')
            count_dinamico = ValorCampo.objects.filter(
                campo=campo_sku, valor__startswith=SKU_PREFIX
            ).count()
            self.stdout.write(f'  Productos dinámicos (SKU L.): {count_dinamico}')

            if count_legacy == count_dinamico:
                self.stdout.write(self.style.SUCCESS('    ✓ Cantidad coincide'))
            else:
                diff = count_legacy - count_dinamico
                self.stdout.write(self.style.ERROR(
                    f'    ✗ DIFERENCIA: {diff} producto(s) sin migrar'
                ))
        except Campo.DoesNotExist:
            self.stdout.write(self.style.WARNING('    ⚠ No se puede verificar (campo sku no existe)'))

        self.stdout.write('')

    def _verificar_clientes(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[2] Verificando clientes...'))

        count_legacy = ClienteLegacy.objects.count()
        self.stdout.write(f'  Clientes legacy:            {count_legacy}')

        try:
            campo_doc = Campo.objects.get(formulario__nombre=FORM_CLIENTES, nombre='documento')
            count_dinamico = ValorCampo.objects.filter(campo=campo_doc).count()
            self.stdout.write(f'  Clientes dinámicos:         {count_dinamico}')

            if count_legacy == count_dinamico:
                self.stdout.write(self.style.SUCCESS('    ✓ Cantidad coincide'))
            else:
                diff = count_legacy - count_dinamico
                self.stdout.write(self.style.ERROR(
                    f'    ✗ DIFERENCIA: {diff} cliente(s) sin migrar'
                ))

            # Verificar fechas de registro
            legacy_documentos = {
                c.documento: c.fecha_registro
                for c in ClienteLegacy.objects.only('documento', 'fecha_registro')
            }
            fechas_incorrectas = 0
            registros_cliente = Registro.objects.filter(
                formulario__nombre=FORM_CLIENTES
            ).only('id', 'fecha_creacion')
            valores_map = DS.cargar_valores_mapa(registros_cliente)
            for r in registros_cliente:
                vals = valores_map.get(r.id, {})
                doc = vals.get('documento', '')
                if doc in legacy_documentos:
                    fecha_legacy = legacy_documentos[doc]
                    if isinstance(fecha_legacy, datetime):
                        if abs((r.fecha_creacion - fecha_legacy).total_seconds()) > 1:
                            fechas_incorrectas += 1
            if fechas_incorrectas > 0:
                self.stdout.write(self.style.WARNING(
                    f'    ⚠ {fechas_incorrectas} cliente(s) con fecha_creacion incorrecta'
                ))
            else:
                self.stdout.write(self.style.SUCCESS('    ✓ Todas las fechas de registro coinciden'))

        except Campo.DoesNotExist:
            self.stdout.write(self.style.WARNING('    ⚠ No se puede verificar (campo documento no existe)'))

        self.stdout.write('')

    def _verificar_ventas(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[3] Verificando ventas...'))

        count_legacy = VentaLegacy.objects.count()
        self.stdout.write(f'  Ventas legacy:              {count_legacy}')

        try:
            campo_id_legacy = Campo.objects.get(formulario__nombre=FORM_VENTAS, nombre='id_legacy')
            count_dinamico = ValorCampo.objects.filter(campo=campo_id_legacy).count()
            self.stdout.write(f'  Ventas dinámicas:           {count_dinamico}')

            if count_legacy == count_dinamico:
                self.stdout.write(self.style.SUCCESS('    ✓ Cantidad coincide'))
            else:
                diff = count_legacy - count_dinamico
                self.stdout.write(self.style.ERROR(
                    f'    ✗ DIFERENCIA: {diff} venta(s) sin migrar'
                ))

            # Verificar totales monetarios
            total_legacy = VentaLegacy.objects.aggregate(
                total=Sum('total')
            )['total'] or Decimal('0')
            self.stdout.write(f'  Total monetario legacy:     ${total_legacy:,.2f}')

            # Sumar totales de ventas dinámicas
            campo_total = Campo.objects.filter(
                formulario__nombre=FORM_VENTAS, nombre='total'
            ).first()
            total_dinamico = Decimal('0')
            if campo_total:
                valores_total = ValorCampo.objects.filter(
                    campo=campo_total,
                    registro__in=Registro.objects.filter(
                        formulario__nombre=FORM_VENTAS,
                        valores__campo=campo_id_legacy,
                    ).distinct()
                )
                for vc_valor in valores_total:
                    total_dinamico += _decimal(vc_valor.valor, 0)
            self.stdout.write(f'  Total monetario dinámico:   ${total_dinamico:,.2f}')

            diff_total = abs(total_legacy - total_dinamico)
            if diff_total < Decimal('0.01'):
                self.stdout.write(self.style.SUCCESS('    ✓ Totales monetarios coinciden'))
            else:
                self.stdout.write(self.style.ERROR(
                    f'    ✗ DIFERENCIA: ${diff_total:,.2f}'
                ))

            # Verificar cantidades vendidas
            cant_legacy = VentaLegacy.objects.aggregate(
                total_cant=Sum('cantidad')
            )['total_cant'] or 0
            self.stdout.write(f'  Cantidades legacy:          {cant_legacy}')

            campo_cant = Campo.objects.filter(
                formulario__nombre=FORM_VENTAS, nombre='cantidad'
            ).first()
            cant_dinamico = 0
            if campo_cant:
                for vc in ValorCampo.objects.filter(
                    campo=campo_cant,
                    registro__in=Registro.objects.filter(
                        formulario__nombre=FORM_VENTAS,
                        valores__campo=campo_id_legacy,
                    ).distinct()
                ):
                    cant_dinamico += _entero(vc.valor, 0)
            self.stdout.write(f'  Cantidades dinámicas:       {cant_dinamico}')

            if cant_legacy == cant_dinamico:
                self.stdout.write(self.style.SUCCESS('    ✓ Cantidades vendidas coinciden'))
            else:
                diff_cant = cant_legacy - cant_dinamico
                self.stdout.write(self.style.ERROR(
                    f'    ✗ DIFERENCIA: {diff_cant} unidad(es)'
                ))

        except Campo.DoesNotExist:
            self.stdout.write(self.style.WARNING('    ⚠ No se puede verificar (campo id_legacy no existe)'))

        self.stdout.write('')

    def _verificar_usuarios_ventas(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[4] Verificando usuarios (vendedores) en ventas...'))

        # Ventas legacy con su vendedor
        legacy_vendedores = {
            v.id: v.vendedor_id
            for v in VentaLegacy.objects.only('id', 'vendedor_id')
        }

        # Ventas dinámicas con su usuario
        try:
            campo_id_legacy = Campo.objects.get(formulario__nombre=FORM_VENTAS, nombre='id_legacy')
            vcs_id = ValorCampo.objects.filter(campo=campo_id_legacy).select_related('registro')
            dinamic_usuarios = {}
            for vc in vcs_id:
                dinamic_usuarios[vc.valor] = vc.registro.usuario_id

            errores = 0
            for legacy_id, vendedor_id in legacy_vendedores.items():
                str_id = str(legacy_id)
                if str_id in dinamic_usuarios:
                    if dinamic_usuarios[str_id] != vendedor_id:
                        errores += 1
                        self.stdout.write(self.style.WARNING(
                            f'    ⚠ Venta #{legacy_id}: vendedor legacy={vendedor_id} != dinámico={dinamic_usuarios[str_id]}'
                        ))

            if errores == 0:
                self.stdout.write(self.style.SUCCESS('    ✓ Todos los vendedores coinciden'))
            else:
                self.stdout.write(self.style.WARNING(
                    f'    ⚠ {errores} venta(s) con vendedor incorrecto'
                ))
        except Campo.DoesNotExist:
            self.stdout.write(self.style.WARNING('    ⚠ No se puede verificar (campo id_legacy no existe)'))

        self.stdout.write('')

    def _verificar_relaciones_rotas(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[5] Verificando relaciones rotas...'))

        # Ventas dinámicas: verificar que producto y cliente existan
        try:
            formulario = Formulario.objects.get(nombre=FORM_VENTAS)
            campo_producto = formulario.campos.filter(nombre='producto').first()
            campo_cliente = formulario.campos.filter(nombre='cliente').first()
            campo_id_legacy = formulario.campos.filter(nombre='id_legacy').first()

            if not campo_producto or not campo_id_legacy:
                self.stdout.write(self.style.WARNING('    ⚠ No se puede verificar relaciones'))
                self.stdout.write('')
                return

            # Productos rotos
            vcs_producto = ValorCampo.objects.filter(campo=campo_producto).select_related('registro')
            productos_rotos = 0
            clientes_rotos = 0

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

    def _verificar_duplicados(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[6] Verificando duplicados...'))

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


def _entero(valor, default=0):
    try:
        return int(str(valor).strip())
    except (ValueError, TypeError):
        return default
