"""
Management command para migrar productos legacy → Dynamic Forms.

Idempotente: puede ejecutarse múltiples veces sin duplicar registros.
Usa el campo `sku` con formato "LEGACY-{id}" como trazabilidad.

Uso:
    python manage.py migrar_productos_dynamic
    python manage.py migrar_productos_dynamic --dry-run
    python manage.py migrar_productos_dynamic --force
"""

import logging
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.legacy.productos.models import Categoria, Producto
from apps.platform.dynamic_forms.models import Campo, Formulario, Registro, ValorCampo
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

logger = logging.getLogger(__name__)

FORM_PRODUCTOS = 'Productos'
FORM_MOVIMIENTOS = 'MovimientosInventario'
SKU_PREFIX = 'LEGACY-'


def _entero(valor, default=0):
    try:
        return int(str(valor).strip())
    except (ValueError, TypeError):
        return default


def _decimal(valor, default=0):
    try:
        return Decimal(str(valor).strip().replace(',', '.'))
    except (ValueError, TypeError):
        return Decimal(str(default))


class Command(BaseCommand):
    help = 'Migra productos legacy (modelo Producto) a Dynamic Forms.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Valida requisitos y muestra lo que se migraría sin escribir BD.'
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Re-migra productos aunque ya exista SKU legacy (actualiza todo).'
        )

    # ==================================================================
    # HANDLE PRINCIPAL
    # ==================================================================

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.force = options['force']

        self.stdout.write(self.style.MIGRATE_HEADING(
            'Migración de Productos Legacy → Dynamic Forms'
        ))
        self.stdout.write(f'  Modo: {"DRY RUN (sin escritura)" if self.dry_run else "EJECUCIÓN"}')
        if self.force:
            self.stdout.write('  Force: re-migrará productos existentes')
        self.stdout.write('')

        # --------------------------------------------------------------
        # 1. Verificar requisitos
        # --------------------------------------------------------------
        if not self._verificar_requisitos():
            self.stdout.write(self.style.ERROR('Migración abortada por requisitos insatisfechos.'))
            return

        # --------------------------------------------------------------
        # 2. Sincronizar categorías
        # --------------------------------------------------------------
        stats_cat = self._sync_categorias()

        # --------------------------------------------------------------
        # 3. Migrar productos
        # --------------------------------------------------------------
        stats_prod = self._migrar_productos()

        # --------------------------------------------------------------
        # 3b. Crear movimientos iniciales faltantes
        # --------------------------------------------------------------
        stats_mov = self._crear_movimientos_faltantes(stats_prod)

        # --------------------------------------------------------------
        # 4. Validaciones finales
        # --------------------------------------------------------------
        validaciones = self._validar_post_migracion()

        # Merge movimientos faltantes into product stats
        stats_prod['movimientos_creados'] += stats_mov.get('creados', 0)
        stats_prod['movimientos_omitidos'] = stats_mov.get('omitidos', 0)

        # --------------------------------------------------------------
        # 5. Reporte final
        # --------------------------------------------------------------
        self._reportar(stats_cat, stats_prod, validaciones)

    # ==================================================================
    # VERIFICACIÓN DE REQUISITOS
    # ==================================================================

    def _verificar_requisitos(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[1/5] Verificando requisitos...'))
        ok = True

        # Formularios
        for nombre_form in [FORM_PRODUCTOS, FORM_MOVIMIENTOS]:
            try:
                f = Formulario.objects.get(nombre=nombre_form)
                self.stdout.write(f'  ✓ Formulario "{nombre_form}" existe (id={f.id})')
            except Formulario.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ Formulario "{nombre_form}" NO existe. '
                    f'Ejecuta: python manage.py sembrar_formularios_base'
                ))
                ok = False

        if not ok:
            return False

        # Campos requeridos en Productos
        campos_requeridos = ['nombre', 'precio', 'stock', 'categoria', 'talla', 'color', 'sku',
                             'imagen', 'imagen_url', 'descripcion', 'stock_minimo', 'activo']
        formulario = Formulario.objects.get(nombre=FORM_PRODUCTOS)
        campos_existentes = {c.nombre for c in formulario.campos.filter(activo=True)}
        for nombre_campo in campos_requeridos:
            if nombre_campo in campos_existentes:
                self.stdout.write(f'  ✓ Campo "{nombre_campo}" existe en Productos')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ Campo "{nombre_campo}" NO existe en Productos'
                ))

        # Campos requeridos en MovimientosInventario
        campos_mov = ['producto', 'tipo', 'cantidad', 'motivo', 'stock_anterior', 'stock_nuevo']
        form_mov = Formulario.objects.get(nombre=FORM_MOVIMIENTOS)
        campos_mov_existentes = {c.nombre for c in form_mov.campos.filter(activo=True)}
        for nombre_campo in campos_mov:
            if nombre_campo in campos_mov_existentes:
                self.stdout.write(f'  ✓ Campo "{nombre_campo}" existe en MovimientosInventario')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ Campo "{nombre_campo}" NO existe en MovimientosInventario'
                ))

        # Productos legacy
        total = Producto.objects.count()
        self.stdout.write(f'  ℹ Productos legacy encontrados: {total}')
        if total == 0:
            self.stdout.write(self.style.WARNING('  ⚠ No hay productos legacy para migrar.'))
            ok = False

        self.stdout.write('')
        return ok

    # ==================================================================
    # SINCRONIZACIÓN DE CATEGORÍAS
    # ==================================================================

    def _sync_categorias(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[2/5] Sincronizando categorías...'))
        stats = {'legacy': 0, 'agregadas': 0, 'ya_existentes': 0, 'final': []}

        # Leer categorías legacy
        categorias_legacy = list(
            Categoria.objects.values_list('nombre', flat=True).order_by('nombre')
        )
        stats['legacy'] = len(categorias_legacy)
        self.stdout.write(f'  Categorías legacy ({len(categorias_legacy)}): {categorias_legacy}')

        # Leer opciones dinámicas actuales
        formulario = Formulario.objects.get(nombre=FORM_PRODUCTOS)
        campo_cat = formulario.campos.filter(activo=True, nombre='categoria').first()

        if not campo_cat:
            self.stdout.write(self.style.ERROR('  ✗ Campo "categoria" no encontrado en Productos'))
            return stats

        opciones_actuales = list(campo_cat.opciones or [])
        self.stdout.write(f'  Opciones dinámicas actuales ({len(opciones_actuales)}): {opciones_actuales}')

        # Construir set unificado
        opciones_finales = list(dict.fromkeys(opciones_actuales + categorias_legacy + ['Otros']))

        # Identificar nuevas
        set_actual = set(opciones_actuales)
        stats['agregadas'] = sum(1 for o in opciones_finales if o not in set_actual)
        stats['ya_existentes'] = sum(1 for o in opciones_finales if o in set_actual)
        stats['final'] = opciones_finales

        if set(opciones_finales) == set_actual:
            self.stdout.write('  ✓ Categorías ya sincronizadas (sin cambios)')
        else:
            self.stdout.write(f'  ✓ Opciones finales ({len(opciones_finales)}): {opciones_finales}')
            nuevas = [o for o in opciones_finales if o not in set_actual]
            self.stdout.write(f'  Nuevas categorías agregadas: {nuevas}')

            if not self.dry_run:
                campo_cat.opciones = opciones_finales
                campo_cat.save(update_fields=['opciones'])
                self.stdout.write(self.style.SUCCESS('  ✓ Campo categoria.opciones actualizado'))

        self.stdout.write('')
        return stats

    # ==================================================================
    # MIGRACIÓN DE PRODUCTOS
    # ==================================================================

    def _normalizar_talla(self, talla):
        """Normaliza valores de talla que difieren por acentos vs opciones dinámicas."""
        mapa = {
            'Única': 'Unica',
            'ú': 'u',
            'Ó': 'O',
            'ó': 'o',
            'Á': 'A',
            'á': 'a',
            'É': 'E',
            'é': 'e',
            'Í': 'I',
            'í': 'i',
        }
        for original, normalizado in mapa.items():
            talla = talla.replace(original, normalizado)
        return talla

    def _sku_legacy(self, producto_id):
        return f'{SKU_PREFIX}{producto_id}'

    def _buscar_por_sku(self, sku):
        """Busca un Registro dinámico por su SKU legacy."""
        try:
            campo_sku = Campo.objects.get(
                formulario__nombre=FORM_PRODUCTOS,
                nombre='sku',
            )
            vc = ValorCampo.objects.get(campo=campo_sku, valor=sku)
            return vc.registro
        except (Campo.DoesNotExist, ValorCampo.DoesNotExist):
            return None

    def _migrar_productos(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[3/5] Migrando productos...'))
        stats = {
            'total_legacy': 0,
            'creados': 0,
            'actualizados': 0,
            'omitidos': 0,
            'errores': [],
            'imagenes_migradas': 0,
            'movimientos_creados': 0,
            'detalle': [],
        }

        productos = Producto.objects.select_related('categoria').order_by('id')
        stats['total_legacy'] = productos.count()
        self.stdout.write(f'  Productos a procesar: {stats["total_legacy"]}')
        self.stdout.write('')

        formulario_mov = Formulario.objects.get(nombre=FORM_MOVIMIENTOS)

        for i, producto in enumerate(productos, 1):
            self.stdout.write(f'  [{i}/{stats["total_legacy"]}] {producto.nombre}... ', ending='')
            try:
                self._migrar_un_producto(producto, stats, formulario_mov)
            except Exception as e:
                stats['errores'].append((producto.id, producto.nombre, str(e)))
                self.stdout.write(self.style.ERROR(f'ERROR: {e}'))
                logger.exception(f'Error migrando producto #{producto.id} "{producto.nombre}"')

        self.stdout.write('')
        return stats

    def _migrar_un_producto(self, producto, stats, formulario_mov=None):
        from django.core.files.base import ContentFile

        sku = self._sku_legacy(producto.id)
        registro_existente = self._buscar_por_sku(sku)

        # Construir valores_dict
        categoria_nombre = producto.categoria.nombre if producto.categoria else ''
        # Normalizar talla: eliminar acentos para coincidir con opciones dinámicas
        talla = self._normalizar_talla(producto.talla or '')
        color = producto.color or ''
        stock_actual = _entero(producto.stock, 0)
        precio = str(producto.precio) if producto.precio else '0'

        valores_dict = {
            'nombre': producto.nombre,
            'precio': precio,
            'stock': str(stock_actual),
            'categoria': categoria_nombre,
            'talla': talla,
            'color': color,
            'sku': sku,
            'descripcion': '',
            'activo': 'Sí',
        }

        # imagen_url: usar URL existente o la final del Cloudinary
        if producto.imagen_final_url:
            valores_dict['imagen_url'] = producto.imagen_final_url
        elif producto.imagen_url:
            valores_dict['imagen_url'] = producto.imagen_url

        # No migramos archivos de imagen físicos — usamos la URL existente
        # (Cloudinary o local). El wrapper DynamicProductWrapper.imagen_final_url
        # prioriza imagen_url sobre imagen subida, por lo que funciona igual.
        archivos_dict = {}
        if producto.imagen_final_url:
            stats['imagenes_migradas'] += 1

        # stock_minimo
        try:
            from apps.shared.configuracion.models import ConfiguracionTienda
            stock_minimo = ConfiguracionTienda.obtener().stock_minimo_alerta
            valores_dict['stock_minimo'] = str(stock_minimo)
        except Exception:
            valores_dict['stock_minimo'] = '5'

        # Determinar si es creación o actualización
        if registro_existente and not self.force:
            # Actualizar producto existente
            if self.dry_run:
                self.stdout.write(f'[ACTUALIZARÍA] ', ending='')
                stats['actualizados'] += 1
            else:
                DS.actualizar(
                    registro_existente,
                    valores_dict,
                    archivos_dict=archivos_dict or None,
                )
                self.stdout.write(self.style.SUCCESS(f'actualizado (id={registro_existente.id}) '), ending='')
                stats['actualizados'] += 1
        else:
            # Crear producto nuevo
            if registro_existente and self.force:
                # Force: primero eliminar el registro existente para recrear
                if not self.dry_run:
                    DS.eliminar(registro_existente)
                    self.stdout.write(f'[force: eliminado #{registro_existente.id}] ', ending='')

            if self.dry_run:
                self.stdout.write(f'[CREARÍA] ', ending='')
                stats['creados'] += 1
            else:
                try:
                    registro = DS.crear(
                        FORM_PRODUCTOS,
                        valores_dict,
                        archivos_dict=archivos_dict or None,
                    )
                    self.stdout.write(self.style.SUCCESS(f'creado (id={registro.id}) '), ending='')
                    stats['creados'] += 1

                    # Crear movimiento de inventario inicial
                    if stock_actual > 0:
                        self._crear_movimiento_inicial(registro, producto, stock_actual,
                                                       formulario_mov)
                        stats['movimientos_creados'] += 1
                except Exception as e:
                    # Re-raise with context
                    raise Exception(f'Error creando producto: {e}') from e

        self.stdout.write('')

    def _crear_movimiento_inicial(self, registro_producto, producto_legacy, stock_actual,
                                  formulario_mov):
        movimiento_data = {
            'producto': str(registro_producto.id),
            'tipo': 'Entrada',
            'cantidad': str(stock_actual),
            'motivo': 'Inventario inicial',
            'stock_anterior': '0',
            'stock_nuevo': str(stock_actual),
            'observacion': f'Migrado desde sistema legacy. Producto original #{producto_legacy.id}',
        }
        try:
            DS.crear(FORM_MOVIMIENTOS, movimiento_data)
        except Exception as e:
            logger.warning(
                f'No se pudo crear movimiento inicial para producto #{producto_legacy.id}: {e}'
            )

    # ==================================================================
    # MOVIMIENTOS INICIALES FALTANTES
    # ==================================================================

    def _sincronizar_motivo_inventario_inicial(self):
        """Agrega 'Inventario inicial' a las opciones del campo motivo si no existe."""
        try:
            campo_motivo = Campo.objects.get(
                formulario__nombre=FORM_MOVIMIENTOS,
                nombre='motivo',
            )
            opciones = list(campo_motivo.opciones or [])
            if 'Inventario inicial' not in opciones:
                opciones.append('Inventario inicial')
                if not self.dry_run:
                    campo_motivo.opciones = opciones
                    campo_motivo.save(update_fields=['opciones'])
                self.stdout.write(f'  ✓ Agregado "Inventario inicial" a opciones de motivo')
        except Campo.DoesNotExist:
            self.stdout.write(self.style.WARNING(
                '  ⚠ Campo "motivo" no encontrado en MovimientosInventario'
            ))

    def _crear_movimientos_faltantes(self, stats_prod):
        self.stdout.write(self.style.MIGRATE_LABEL('[3b/5] Creando movimientos iniciales faltantes...'))
        stats = {'creados': 0, 'omitidos': 0, 'errores': 0}

        if self.dry_run:
            self.stdout.write('  (omitido en dry-run)')
            return stats

        # Asegurar que 'Inventario inicial' esté en opciones de motivo
        self._sincronizar_motivo_inventario_inicial()

        # Obtener todos los SKU migrados
        campo_sku = Campo.objects.get(formulario__nombre=FORM_PRODUCTOS, nombre='sku')
        vcs = ValorCampo.objects.filter(
            campo=campo_sku, valor__startswith=SKU_PREFIX
        ).select_related('registro')

        if not vcs:
            self.stdout.write('  ℹ No hay productos migrados para procesar')
            return stats

        # IDs de productos dinámicos migrados
        registro_ids_migrados = {vc.registro_id for vc in vcs}
        str_ids = {str(i) for i in registro_ids_migrados}

        # Obtener registros de MovimientosInventario que sean "Inventario inicial"
        campo_motivo = Campo.objects.get(
            formulario__nombre=FORM_MOVIMIENTOS, nombre='motivo'
        )
        movs_iniciales_ids = set(
            ValorCampo.objects.filter(
                campo=campo_motivo, valor='Inventario inicial'
            ).values_list('registro_id', flat=True)
        )

        # De esos movimientos, qué producto referencia cada uno
        campo_producto = Campo.objects.get(
            formulario__nombre=FORM_MOVIMIENTOS, nombre='producto'
        )
        productos_con_movimiento = set(
            ValorCampo.objects.filter(
                campo=campo_producto,
                registro_id__in=movs_iniciales_ids,
                valor__in=str_ids,
            ).values_list('valor', flat=True)
        )

        faltantes = [
            (vc.registro_id, vc.valor)
            for vc in vcs
            if str(vc.registro_id) not in productos_con_movimiento
        ]

        if not faltantes:
            self.stdout.write('  ✓ Todos los productos migrados tienen movimiento inicial')
            return stats

        self.stdout.write(f'  ℹ Productos sin movimiento inicial: {len(faltantes)}')

        for reg_id, sku in faltantes:
            try:
                # Obtener stock actual del producto dinámico
                stock_val = DS.obtener_valor(
                    Registro.objects.get(id=reg_id), 'stock', '0'
                )
                stock_actual = _entero(stock_val, 0)
                if stock_actual <= 0:
                    stats['omitidos'] += 1
                    continue

                DS.crear(FORM_MOVIMIENTOS, {
                    'producto': str(reg_id),
                    'tipo': 'Entrada',
                    'cantidad': str(stock_actual),
                    'motivo': 'Inventario inicial',
                    'stock_anterior': '0',
                    'stock_nuevo': str(stock_actual),
                    'observacion': f'Migrado desde sistema legacy. SKU: {sku}',
                })
                stats['creados'] += 1
                self.stdout.write(f'    ✓ Movimiento creado para Registro #{reg_id} ({sku})')
            except Exception as e:
                stats['errores'] += 1
                logger.warning(f'Error creando movimiento para #{reg_id}: {e}')
                self.stdout.write(self.style.WARNING(f'    ⚠ Error en #{reg_id}: {e}'))

        self.stdout.write('')
        return stats

    # ==================================================================
    # VALIDACIONES POST-MIGRACIÓN
    # ==================================================================

    def _validar_post_migracion(self):
        self.stdout.write(self.style.MIGRATE_LABEL('[4/5] Validando post-migración...'))
        validaciones = defaultdict(list)

        if self.dry_run:
            self.stdout.write('  (omitido en dry-run)')
            self.stdout.write('')
            return dict(validaciones)

        # Productos migrados
        campo_sku = Campo.objects.get(formulario__nombre=FORM_PRODUCTOS, nombre='sku')
        vcs = ValorCampo.objects.filter(
            campo=campo_sku,
            valor__startswith=SKU_PREFIX,
        )
        skus_encontrados = {vc.valor for vc in vcs}

        legacy_ids_esperados = set(Producto.objects.values_list('id', flat=True))
        legacy_ids_migrados = {int(v.replace(SKU_PREFIX, '')) for v in skus_encontrados}

        # Productos sin migrar
        no_migrados = legacy_ids_esperados - legacy_ids_migrados
        if no_migrados:
            validaciones['productos_no_migrados'] = sorted(no_migrados)
            nombres = list(
                Producto.objects.filter(id__in=no_migrados).values_list('nombre', flat=True)
            )
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Productos legacy sin migrar ({len(no_migrados)}): {nombres}'
            ))

        # Productos migrados con SKU no legacy
        skus_no_legacy = ValorCampo.objects.filter(
            campo=campo_sku,
        ).exclude(valor__startswith=SKU_PREFIX).exclude(valor='').count()
        if skus_no_legacy > 0:
            validaciones['productos_con_sku_propio'] = skus_no_legacy
            self.stdout.write(f'  ℹ Productos con SKU propio (no legacy): {skus_no_legacy}')

        # Migrados totales
        total_migrados = len(skus_encontrados)
        validaciones['total_migrados'] = total_migrados
        self.stdout.write(f'  ✓ Productos migrados exitosamente: {total_migrados}')

        total_legacy = Producto.objects.count()
        if total_migrados >= total_legacy:
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ Cobertura: {total_migrados}/{total_legacy} (100%)'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Cobertura: {total_migrados}/{total_legacy} '
                f'({total_migrados * 100 // total_legacy if total_legacy else 0}%)'
            ))
            validaciones['cobertura_parcial'] = True

        # Verificar categorías en opciones
        categorias_en_uso = set(
            ValorCampo.objects.filter(
                campo__formulario__nombre=FORM_PRODUCTOS,
                campo__nombre='categoria',
            ).exclude(valor='').values_list('valor', flat=True)
        )
        campo_cat = Campo.objects.get(formulario__nombre=FORM_PRODUCTOS, nombre='categoria')
        opciones_disponibles = set(campo_cat.opciones or [])
        categorias_faltantes = categorias_en_uso - opciones_disponibles
        if categorias_faltantes:
            validaciones['categorias_faltantes'] = list(categorias_faltantes)
            self.stdout.write(self.style.ERROR(
                f'  ✗ Categorías en uso pero no en opciones: {list(categorias_faltantes)}'
            ))
        else:
            self.stdout.write('  ✓ Todas las categorías en uso están en opciones')

        # Productos sin imagen
        sin_imagen = Registro.objects.filter(
            formulario__nombre=FORM_PRODUCTOS,
        ).exclude(
            valores__campo__nombre='imagen',
        ).exclude(
            valores__campo__nombre='imagen_url',
        ).count()
        if sin_imagen > 0:
            validaciones['productos_sin_imagen'] = sin_imagen
            self.stdout.write(f'  ℹ Productos sin imagen: {sin_imagen}')

        self.stdout.write('')
        return dict(validaciones)

    # ==================================================================
    # REPORTE FINAL
    # ==================================================================

    def _reportar(self, stats_cat, stats_prod, validaciones):
        self.stdout.write(self.style.MIGRATE_LABEL('[5/5] Resumen final'))
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 55))
        self.stdout.write(self.style.MIGRATE_HEADING('  RESUMEN DE MIGRACIÓN'))
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 55))
        self.stdout.write('')

        # Categorías
        self.stdout.write('  Categorías:')
        self.stdout.write(f'    Legacy encontradas:     {stats_cat["legacy"]}')
        self.stdout.write(f'    Agregadas a opciones:   {stats_cat["agregadas"]}')
        self.stdout.write(f'    Ya existentes:          {stats_cat["ya_existentes"]}')
        self.stdout.write(f'    Opciones finales:       {len(stats_cat["final"])}')
        self.stdout.write('')

        # Productos
        self.stdout.write('  Productos:')
        self.stdout.write(f'    Legacy encontrados:     {stats_prod["total_legacy"]}')
        self.stdout.write(f'    Creados:                {stats_prod["creados"]}')
        self.stdout.write(f'    Actualizados:           {stats_prod["actualizados"]}')
        self.stdout.write(f'    Omitidos:               {stats_prod["omitidos"]}')
        self.stdout.write(f'    Imágenes migradas:      {stats_prod["imagenes_migradas"]}')
        self.stdout.write(f'    Movs. inventario inic.: {stats_prod["movimientos_creados"]}')
        self.stdout.write(f'    Errores:                {len(stats_prod["errores"])}')
        self.stdout.write('')

        if stats_prod['errores']:
            self.stdout.write(self.style.ERROR('  Errores:'))
            for prod_id, nombre, error in stats_prod['errores']:
                self.stdout.write(f'    #{prod_id} "{nombre}": {error}')
            self.stdout.write('')

        if validaciones:
            self.stdout.write('  Validaciones:')
            if 'total_migrados' in validaciones:
                pct = validaciones['total_migrados'] * 100 // max(stats_prod['total_legacy'], 1)
                self.stdout.write(f'    Cobertura:              {pct}%')
            if 'productos_no_migrados' in validaciones:
                self.stdout.write(self.style.WARNING(
                    f'    Productos no migrados:  {len(validaciones["productos_no_migrados"])}'
                ))
            if 'productos_sin_imagen' in validaciones:
                self.stdout.write(
                    f'    Productos sin imagen:   {validaciones["productos_sin_imagen"]}'
                )
            self.stdout.write('')

        # Estado general
        errores = len(stats_prod['errores'])
        if errores == 0 and (stats_prod['creados'] > 0 or stats_prod['actualizados'] > 0):
            self.stdout.write(self.style.SUCCESS('  ✅ Migración completada exitosamente'))
        elif errores == 0 and stats_prod['creados'] == 0 and stats_prod['actualizados'] == 0:
            self.stdout.write(self.style.WARNING('  ⚠ No se realizaron cambios'))
        else:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Migración completada con {errores} error(es)'
            ))
        self.stdout.write('')
