"""
DynamicService — Capa de abstracción sobre dynamic_forms.

Permite que los módulos funcionales (productos, ventas, clientes, etc.)
operen sobre Formulario → Campo → Registro → ValorCampo sin conocer
los detalles internos del modelo EAV.

Uso típico desde una vista legacy:

    from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

    # Listar productos
    registros = DS.filtrar('Productos', activo='Sí')

    # Crear producto
    registro = DS.crear('Productos', {
        'nombre': 'Camisa Azul',
        'precio': '50000',
        'stock': '10',
        'categoria': 'Ropa',
    }, usuario=request.user)

    # Obtener valor
    nombre = DS.obtener_valor(registro, 'nombre')
"""

import logging
import os
import threading
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    Campo,
    Formulario,
    Registro,
    ValorCampo,
    _importar_funcion,
)

logger = logging.getLogger(__name__)


# ======================================================================
# HELPER PARA SUBIDA DE ARCHIVOS
# ======================================================================


_EXTENSIONES_PERMITIDAS_SUBIDA: set[str] = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',  # imágenes
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',           # documentos
    '.txt', '.csv', '.zip', '.rar',                     # otros
}

_MAX_TAMANO_SUBIDA: int = 20 * 1024 * 1024  # 20 MB


def _guardar_archivo_subido(archivo, campo_nombre, formulario_nombre):
    """Guarda un archivo/imagen en MEDIA_ROOT/dynamic_uploads/ y devuelve la URL.

    Seguridad:
      - Solo permite extensiones de la lista blanca.
      - Rechaza archivos > 20 MB.
      - Genera nombre UUID (previene path traversal).
    """
    if archivo.size > _MAX_TAMANO_SUBIDA:
        raise ValueError(
            f'El archivo excede el tamaño máximo de '
            f'{_MAX_TAMANO_SUBIDA // (1024 * 1024)} MB.'
        )

    ext = Path(archivo.name).suffix.lower()
    if ext not in _EXTENSIONES_PERMITIDAS_SUBIDA:
        raise ValueError(
            f'Extensión "{ext}" no permitida para subida de archivos.'
        )

    dir_upload = Path(settings.MEDIA_ROOT) / 'dynamic_uploads'
    os.makedirs(dir_upload, exist_ok=True)

    nombre_archivo = f"{formulario_nombre}_{campo_nombre}_{uuid.uuid4().hex[:12]}{ext}"
    ruta = dir_upload / nombre_archivo

    with open(ruta, 'wb') as f:
        for chunk in archivo.chunks():
            f.write(chunk)

    return f"{settings.MEDIA_URL}dynamic_uploads/{nombre_archivo}"


# ======================================================================
# PROTECCIÓN CONTRA RECURSIÓN DE HOOKS
# ======================================================================
# Usa thread-local storage para detectar y prevenir ciclos infinitos
# cuando un hook llama a DS.crear() que a su vez ejecuta el mismo hook.

_hook_local = threading.local()


class HookRecursivoError(Exception):
    """Se lanza cuando se detecta recursión de hooks."""
    pass


def _ejecucion_hooks_activa():
    """Retorna True si ya hay un hook en ejecución en este hilo."""
    return getattr(_hook_local, 'activo', False)


def _marcar_inicio_hook():
    """Marca el inicio de ejecución de un hook."""
    _hook_local.activo = True


def _marcar_fin_hook():
    """Marca el fin de ejecución de un hook."""
    _hook_local.activo = False


# ======================================================================
# CONSTANTES — Nombres de formularios del sistema
# ======================================================================

FORM_PRODUCTOS = 'Productos'
FORM_CLIENTES = 'Clientes'
FORM_VENTAS = 'Ventas'
FORM_MOVIMIENTOS_INVENTARIO = 'MovimientosInventario'

FORMULARIOS_SISTEMA = [
    FORM_PRODUCTOS,
    FORM_CLIENTES,
    FORM_VENTAS,
    FORM_MOVIMIENTOS_INVENTARIO,
]


# ======================================================================
# EXCEPCIONES
# ======================================================================


class DynamicFormError(Exception):
    """Error base del servicio dinámico."""
    pass


class FormularioNoEncontrado(DynamicFormError):
    pass


class CampoNoEncontrado(DynamicFormError):
    pass


class ValidacionError(DynamicFormError):
    def __init__(self, errores):
        self.errores = errores if isinstance(errores, list) else [errores]
        super().__init__('; '.join(self.errores))


class ValorUnicoError(ValidacionError):
    pass


# ======================================================================
# SERVICIO PRINCIPAL
# ======================================================================


class DynamicService:

    # ------------------------------------------------------------------
    # UTILIDADES
    # ------------------------------------------------------------------

    @staticmethod
    def obtener_formulario(nombre, raise_if_missing=True):
        """Retorna el Formulario por nombre. Opcionalmente lanza error."""
        try:
            return Formulario.objects.get(nombre=nombre)
        except Formulario.DoesNotExist:
            if raise_if_missing:
                raise FormularioNoEncontrado(
                    f'No existe un formulario llamado "{nombre}". '
                    f'Debes ejecutar el seed de formularios base primero.'
                )
            return None

    @staticmethod
    def obtener_campo(formulario, nombre_campo, raise_if_missing=True):
        """Retorna un Campo por nombre dentro de un Formulario."""
        try:
            return formulario.campos.filter(activo=True).get(nombre=nombre_campo)
        except Campo.DoesNotExist:
            if raise_if_missing:
                raise CampoNoEncontrado(
                    f'No existe el campo "{nombre_campo}" en el formulario "{formulario.nombre}".'
                )
            return None

    @staticmethod
    def _campos_activos(formulario):
        return formulario.campos.filter(activo=True).order_by('orden')

    @staticmethod
    def obtener_campos_activos(nombre_formulario):
        """
        Retorna los campos activos de un formulario por su nombre,
        ordenados por el campo 'orden'.

        Args:
            nombre_formulario: Nombre del formulario (ej: 'Productos')

        Returns:
            QuerySet de Campo filtrado por activo=True, ordenado por 'orden'.
            Retorna lista vacía si el formulario no existe.
        """
        formulario = DynamicService.obtener_formulario(nombre_formulario, raise_if_missing=False)
        if formulario is None:
            return []
        return DynamicService._campos_activos(formulario)

    # ------------------------------------------------------------------
    # LECTURA DE VALORES
    # ------------------------------------------------------------------

    @staticmethod
    def obtener_valor(registro, nombre_campo, default=''):
        """
        Retorna el valor de un campo en un registro.

        Args:
            registro: Instancia de Registro
            nombre_campo: Nombre del campo (string)
            default: Valor por defecto si no existe

        Returns:
            String con el valor, o default si no existe
        """
        try:
            vc = registro.valores.get(campo__nombre=nombre_campo)
            return vc.valor
        except ValorCampo.DoesNotExist:
            return default

    @staticmethod
    def obtener_valores(registro):
        """
        Retorna un dict {nombre_campo: valor} con todos los valores de un registro.

        Útil para pasar a templates que esperan un objeto con atributos.
        """
        resultado = {
            'id': registro.id,
            'fecha_creacion': registro.fecha_creacion,
            'fecha_actualizacion': registro.fecha_actualizacion,
            'usuario_id': registro.usuario_id,
        }
        for vc in registro.valores.select_related('campo').all():
            resultado[vc.campo.nombre] = vc.valor
        return resultado

    @staticmethod
    def cargar_valores_mapa(registros, formulario=None):
        """
        Precarga los valores de múltiples registros en un dict.

        Args:
            registros: QuerySet o lista de Registro
            formulario: Opcional. Si se pasa, solo carga campos activos de ese formulario.

        Returns:
            {registro_id: {campo_nombre: valor, ...}, ...}
        """
        qs = ValorCampo.objects.filter(registro__in=registros)
        if formulario:
            campos_activos = {c.id for c in DynamicService._campos_activos(formulario)}
            qs = qs.filter(campo_id__in=campos_activos)

        mapa = defaultdict(dict)
        for vc in qs.select_related('campo').all():
            mapa[vc.registro_id][vc.campo.nombre] = vc.valor
        return dict(mapa)

    # ------------------------------------------------------------------
    # FILTRADO / BÚSQUEDA
    # ------------------------------------------------------------------

    @staticmethod
    def filtrar(nombre_formulario, order_by='-fecha_creacion', **filtros_campos):
        """
        Filtra registros de un formulario por valores de campo.

        Args:
            nombre_formulario: Nombre del formulario
            order_by: Criterio de ordenación
            **filtros_campos: Pares campo_nombre=valor a filtrar

        Returns:
            QuerySet de Registro (con valores precargables)
        """
        formulario = DynamicService.obtener_formulario(nombre_formulario)
        registros = Registro.objects.filter(formulario=formulario)

        if filtros_campos:
            # Construir subquery: IDs de registros que tienen TODOS los valores buscados
            for campo_nombre, valor_buscado in filtros_campos.items():
                campo = DynamicService.obtener_campo(formulario, campo_nombre)
                registros = registros.filter(
                    valores__campo=campo,
                    valores__valor=valor_buscado
                )

        return registros.order_by(order_by)

    @staticmethod
    def buscar(nombre_formulario, texto_busqueda, campos_busqueda=None, order_by='-fecha_creacion'):
        """
        Búsqueda textual en los campos de un formulario.

        Args:
            nombre_formulario: Nombre del formulario
            texto_busqueda: Texto a buscar
            campos_busqueda: Lista de nombres de campo donde buscar.
                             Si es None, busca en todos los campos de tipo texto.
            order_by: Criterio de ordenación

        Returns:
            QuerySet de Registro
        """
        formulario = DynamicService.obtener_formulario(nombre_formulario)
        registros = Registro.objects.filter(formulario=formulario)

        if not texto_busqueda:
            return registros.order_by(order_by)

        if campos_busqueda is None:
            # Buscar en campos de texto por defecto
            campos = formulario.campos.filter(
                activo=True,
                tipo__in=['texto', 'textarea', 'email', 'telefono']
            )
        else:
            campos = formulario.campos.filter(activo=True, nombre__in=campos_busqueda)

        if not campos:
            return registros.order_by(order_by)

        # Construir Q objects para OR entre campos
        q_objects = Q()
        for campo in campos:
            q_objects |= Q(valores__campo=campo, valores__valor__icontains=texto_busqueda)

        registros = registros.filter(q_objects).distinct()
        return registros.order_by(order_by)

    # ------------------------------------------------------------------
    # AGREGACIONES
    # ------------------------------------------------------------------

    @staticmethod
    def sumar(nombre_formulario, nombre_campo, **filtros_campos):
        """
        Suma los valores numéricos de un campo en los registros filtrados.

        Args:
            nombre_formulario: Nombre del formulario
            nombre_campo: Nombre del campo numérico
            **filtros_campos: Filtros adicionales

        Returns:
            Decimal con la suma total
        """
        registros = DynamicService.filtrar(nombre_formulario, **filtros_campos)
        formulario = DynamicService.obtener_formulario(nombre_formulario)
        campo = DynamicService.obtener_campo(formulario, nombre_campo)

        total = Decimal('0')
        for vc in ValorCampo.objects.filter(
            registro__in=registros,
            campo=campo
        ).values_list('valor', flat=True):
            try:
                total += Decimal(str(vc).replace(',', '.'))
            except (ValueError, TypeError):
                pass
        return total

    @staticmethod
    def contar(nombre_formulario, **filtros_campos):
        """Cuenta los registros que coinciden con los filtros."""
        return DynamicService.filtrar(nombre_formulario, **filtros_campos).count()

    @staticmethod
    def top(nombre_formulario, nombre_campo_valor, nombre_campo_agrupador=None,
            limite=5, **filtros_campos):
        """
        Retorna los registros agrupados por un campo, ordenados por suma descendente.

        Args:
            nombre_formulario: Nombre del formulario
            nombre_campo_valor: Campo numérico a sumar (ej: 'total', 'cantidad')
            nombre_campo_agrupador: Campo por el que agrupar (ej: 'producto').
                                    Si es None, usa el primer campo texto del formulario.
            limite: Cantidad máxima de resultados
            **filtros_campos: Filtros adicionales

        Returns:
            Lista de dicts con {nombre, cantidad, total}
        """
        registros = DynamicService.filtrar(nombre_formulario, **filtros_campos)
        formulario = DynamicService.obtener_formulario(nombre_formulario)

        campo_valor = DynamicService.obtener_campo(formulario, nombre_campo_valor)

        if nombre_campo_agrupador:
            campo_agrupador = DynamicService.obtener_campo(formulario, nombre_campo_agrupador)
        else:
            campo_agrupador = formulario.campos.filter(
                activo=True, tipo='texto'
            ).order_by('orden').first()

        if not campo_agrupador:
            return []

        # --- Construir mapas en una sola pasada ---
        # Mapa 1: registro_id → nombre del grupo
        # Mapa 2: registro_id → valor numérico
        valores_qs = ValorCampo.objects.filter(
            registro__in=registros,
            campo__in=[campo_valor, campo_agrupador]
        ).values_list('registro_id', 'campo__nombre', 'valor')

        mapa_grupo = {}    # {registro_id: nombre_grupo}
        mapa_valor = {}    # {registro_id: Decimal(valor)}

        for reg_id, camp_nombre, valor in valores_qs:
            if camp_nombre == campo_agrupador.nombre:
                mapa_grupo[reg_id] = valor
            elif camp_nombre == campo_valor.nombre:
                try:
                    mapa_valor[reg_id] = Decimal(str(valor).replace(',', '.'))
                except (ValueError, TypeError):
                    mapa_valor[reg_id] = Decimal('0')

        # --- Agregar en una pasada ---
        agrupado = defaultdict(lambda: {'cantidad': 0, 'total': Decimal('0')})
        for reg_id, num_val in mapa_valor.items():
            nombre_grupo = mapa_grupo.get(reg_id, f'#{reg_id}')
            agrupado[nombre_grupo]['cantidad'] += 1
            agrupado[nombre_grupo]['total'] += num_val

        resultado = [
            {'nombre': k, 'cantidad': v['cantidad'], 'total': v['total']}
            for k, v in agrupado.items()
        ]
        resultado.sort(key=lambda x: x['total'], reverse=True)
        return resultado[:limite]

    # ------------------------------------------------------------------
    # VALIDACIONES
    # ------------------------------------------------------------------

    @staticmethod
    def validar_unicidad(formulario, nombre_campo, valor, excluir_registro_id=None):
        """
        Valida que un valor sea único en un campo marcado como 'unico'.

        Returns:
            None si es válido. Lanza ValorUnicoError si ya existe.
        """
        campo = DynamicService.obtener_campo(formulario, nombre_campo)
        if not campo.unico:
            return

        qs = ValorCampo.objects.filter(campo=campo, valor=valor)
        if excluir_registro_id:
            qs = qs.exclude(registro_id=excluir_registro_id)

        if qs.exists():
            raise ValorUnicoError(
                f'El valor "{valor}" ya existe en el campo "{campo.nombre}". '
                'Debe ser único.'
            )

    @staticmethod
    def ejecutar_validacion_personalizada(formulario, valores_dict):
        """
        Ejecuta la función de validación personalizada definida en el formulario.

        La función debe tener la firma:
            def mi_validacion(formulario, valores_dict) -> list[str]

        Args:
            formulario: Instancia de Formulario
            valores_dict: Dict {nombre_campo: valor}

        Returns:
            Lista de errores (vacía si no hay errores)
        """
        if not formulario.validacion_personalizada:
            return []

        fn = _importar_funcion(formulario.validacion_personalizada)
        if fn is None:
            return [f'No se pudo cargar la validación: {formulario.validacion_personalizada}']

        try:
            errores = fn(formulario, valores_dict)
            return errores if isinstance(errores, list) else [str(errores)]
        except Exception as e:
            logger.exception(f'Error en validación personalizada de {formulario.nombre}: {e}')
            return [f'Error en validación personalizada: {e}']

    @staticmethod
    def validar_campos_obligatorios(formulario, valores_dict):
        """Valida que los campos obligatorios tengan valor."""
        errores = []
        for campo in DynamicService._campos_activos(formulario):
            if campo.obligatorio:
                valor = valores_dict.get(campo.nombre, '').strip()
                if not valor:
                    errores.append(f'El campo "{campo.nombre}" es obligatorio.')
        return errores

    @staticmethod
    def validar_tipos(formulario, valores_dict):
        """Valida tipos de campo usando el módulo validators."""
        from .validators import _validar_valor_campo

        errores = []
        for campo in DynamicService._campos_activos(formulario):
            valor = valores_dict.get(campo.nombre, '').strip()
            if valor:
                _, error = _validar_valor_campo(campo, valor)
                if error:
                    errores.append(error)
        return errores

    @staticmethod
    def validar_completo(formulario, valores_dict, excluir_registro_id=None):
        """
        Ejecuta todas las validaciones disponibles para un formulario.

        Returns:
            Lista de errores. Vacía si todo es válido.
        """
        errores = []

        # 1. Campos obligatorios
        errores.extend(DynamicService.validar_campos_obligatorios(formulario, valores_dict))

        # 2. Validación de tipos
        errores.extend(DynamicService.validar_tipos(formulario, valores_dict))

        # 3. Unicidad
        for campo in DynamicService._campos_activos(formulario):
            if campo.unico:
                valor = valores_dict.get(campo.nombre, '').strip()
                if valor:
                    try:
                        DynamicService.validar_unicidad(
                            formulario, campo.nombre, valor, excluir_registro_id
                        )
                    except ValorUnicoError as e:
                        errores.extend(e.errores)

        # 4. Validación personalizada
        errores.extend(DynamicService.ejecutar_validacion_personalizada(formulario, valores_dict))

        return errores

    # ------------------------------------------------------------------
    # CREACIÓN DE REGISTROS
    # ------------------------------------------------------------------

    @staticmethod
    def _guardar_valores_no_calculados(
        registro, formulario, valores_dict, archivos_dict, valores_guardados, usar_update_or_create=False
    ) -> None:
        """
        Primera pasada: guarda los valores enviados (excepto calculados) en ValorCampo.
        Compartido entre crear() y actualizar().
        """
        for campo in DynamicService._campos_activos(formulario):
            if campo.tipo == 'calculado':
                continue

            if campo.tipo in Campo.TIPOS_ARCHIVO and archivos_dict:
                archivo = archivos_dict.get(campo.nombre)
                if archivo:
                    valor = _guardar_archivo_subido(archivo, campo.nombre, formulario.nombre)
                    if usar_update_or_create:
                        ValorCampo.objects.update_or_create(
                            registro=registro, campo=campo, defaults={'valor': valor}
                        )
                    else:
                        ValorCampo.objects.create(registro=registro, campo=campo, valor=valor)
                    valores_guardados[campo.nombre] = valor
                continue

            if campo.nombre not in valores_dict:
                if usar_update_or_create:
                    # En actualizar, conservar valor existente si no viene en valores_dict
                    continue
                # En crear, no guardar si no está en el dict
                continue

            valor = valores_dict[campo.nombre].strip()
            if valor:
                if usar_update_or_create:
                    ValorCampo.objects.update_or_create(
                        registro=registro, campo=campo, defaults={'valor': valor}
                    )
                else:
                    ValorCampo.objects.create(registro=registro, campo=campo, valor=valor)
                valores_guardados[campo.nombre] = valor
            elif usar_update_or_create:
                ValorCampo.objects.filter(registro=registro, campo=campo).delete()
                valores_guardados.pop(campo.nombre, None)

    @staticmethod
    def _recalcular_campos_calculados(registro, formulario, valores_guardados, usar_update_or_create=False) -> None:
        """
        Segunda pasada: recalcula campos calculados después de guardar valores normales.
        Soporta encadenamiento (ej: subtotal → total = subtotal - descuento).
        """
        for campo in DynamicService._campos_activos(formulario):
            if campo.tipo == 'calculado' and campo.formula:
                from .services import _evaluar_formula
                resultado = _evaluar_formula(campo.formula, valores_guardados)
                if usar_update_or_create:
                    ValorCampo.objects.update_or_create(
                        registro=registro, campo=campo, defaults={'valor': resultado}
                    )
                else:
                    ValorCampo.objects.create(registro=registro, campo=campo, valor=resultado)
                valores_guardados[campo.nombre] = resultado

    @staticmethod
    def crear(nombre_formulario, valores_dict, usuario=None, usar_select_for_update=False,
              archivos_dict=None):
        """
        Crea un registro en un formulario dinámico con validación completa,
        recálculo de campos calculados, subida de archivos y ejecución de hooks.

        Args:
            nombre_formulario: Nombre del formulario
            valores_dict: Dict {nombre_campo: valor}
            usuario: Usuario opcional que crea el registro
            usar_select_for_update: Si True, bloquea el formulario para escritura
            archivos_dict: Dict opcional {nombre_campo: UploadedFile} para campos
                          de tipo 'imagen' o 'archivo'

        Returns:
            Instancia de Registro creado

        Raises:
            ValidacionError: Si hay errores de validación
        """
        formulario = DynamicService.obtener_formulario(nombre_formulario)

        errores = DynamicService.validar_completo(formulario, valores_dict)
        if errores:
            raise ValidacionError(errores)

        with transaction.atomic():
            if usar_select_for_update:
                list(Formulario.objects.select_for_update().filter(id=formulario.id))

            registro = Registro.objects.create(formulario=formulario, usuario=usuario)

            valores_guardados: dict[str, str] = {}
            DynamicService._guardar_valores_no_calculados(
                registro, formulario, valores_dict, archivos_dict, valores_guardados
            )
            DynamicService._recalcular_campos_calculados(registro, formulario, valores_guardados)

            DynamicService._ejecutar_hook(formulario.hook_post_crear, registro)

        return registro

    @staticmethod
    def actualizar(registro, valores_dict, usuario=None, usar_select_for_update=False,
                   archivos_dict=None):
        """
        Actualiza los valores de un registro existente.
        Recalcula campos calculados, reemplaza archivos y ejecuta hooks.

        Args:
            registro: Instancia de Registro a actualizar
            valores_dict: Dict {nombre_campo: valor} con los nuevos valores
            usuario: Usuario opcional
            usar_select_for_update: Si True, bloquea el registro para escritura
            archivos_dict: Dict opcional {nombre_campo: UploadedFile} para campos
                          de tipo 'imagen' o 'archivo'

        Returns:
            El mismo registro actualizado

        Raises:
            ValidacionError: Si hay errores de validación
        """
        formulario = registro.formulario

        errores = DynamicService.validar_completo(
            formulario, valores_dict, excluir_registro_id=registro.id
        )
        if errores:
            raise ValidacionError(errores)

        with transaction.atomic():
            if usar_select_for_update:
                list(Registro.objects.select_for_update().filter(id=registro.id))

            registro.save(update_fields=['fecha_actualizacion'])

            valores_guardados: dict[str, str] = {}
            for vc in registro.valores.select_related('campo').all():
                if vc.campo.tipo != 'calculado':
                    valores_guardados[vc.campo.nombre] = vc.valor

            DynamicService._guardar_valores_no_calculados(
                registro, formulario, valores_dict, archivos_dict, valores_guardados,
                usar_update_or_create=True
            )
            DynamicService._recalcular_campos_calculados(
                registro, formulario, valores_guardados, usar_update_or_create=True
            )

            DynamicService._ejecutar_hook(formulario.hook_post_actualizar, registro)

        return registro

    @staticmethod
    def _ejecutar_hook(path_funcion, registro):
        """
        Ejecuta un hook si está definido, con protección contra recursión.

        Usa thread-local storage para detectar si ya hay un hook en ejecución
        en el mismo hilo. Si se detecta recursión, lanza HookRecursivoError
        para evitar ciclos infinitos.
        """
        if not path_funcion:
            return

        # --- Protección contra recursión ---
        if _ejecucion_hooks_activa():
            logger.error(
                f'Recursión de hooks detectada: "{path_funcion}" '
                f'intentó ejecutarse mientras otro hook ya estaba activo '
                f'en registro #{registro.id}. Ciclo interrumpido.'
            )
            raise HookRecursivoError(
                f'Recursión de hooks detectada en "{path_funcion}". '
                'No se puede ejecutar un hook dentro de otro hook.'
            )

        fn = _importar_funcion(path_funcion)
        if fn is None:
            logger.warning(f'Hook "{path_funcion}" no encontrado para registro #{registro.id}')
            return

        _marcar_inicio_hook()
        try:
            fn(registro)
        except Exception as e:
            logger.exception(
                f'Error ejecutando hook "{path_funcion}" en registro #{registro.id}: {e}'
            )
            raise
        finally:
            _marcar_fin_hook()

    # ------------------------------------------------------------------
    # IDENTIFICADOR PRINCIPAL
    # ------------------------------------------------------------------

    @staticmethod
    def obtener_identificador_principal(nombre_formulario):
        """
        Retorna el campo marcado como identificador principal de un formulario.

        Args:
            nombre_formulario: Nombre del formulario

        Returns:
            Campo o None si no hay identificador principal
        """
        formulario = DynamicService.obtener_formulario(nombre_formulario, raise_if_missing=False)
        if formulario is None:
            return None
        return formulario.campos.filter(activo=True, identificador_principal=True).first()

    @staticmethod
    def buscar_por_identificador(nombre_formulario, valor_identificador):
        """
        Busca un registro por el valor de su identificador principal.

        Preparado para futura integración con importaciones, upsert y sincronización.

        Args:
            nombre_formulario: Nombre del formulario
            valor_identificador: Valor del identificador principal a buscar

        Returns:
            Registro o None si no se encuentra
        """
        campo_id = DynamicService.obtener_identificador_principal(nombre_formulario)
        if campo_id is None:
            return None
        try:
            vc = ValorCampo.objects.get(campo=campo_id, valor=str(valor_identificador))
            return vc.registro
        except ValorCampo.DoesNotExist:
            return None

    @staticmethod
    def upsert_por_identificador(nombre_formulario, valores_dict, usuario=None):
        """
        Crea o actualiza un registro basándose en el valor del identificador principal.

        Preparado para futura integración con importaciones y sincronización.
        Si el identificador principal existe en la BD, actualiza; si no, crea.

        Args:
            nombre_formulario: Nombre del formulario
            valores_dict: Dict {nombre_campo: valor}
            usuario: Usuario opcional

        Returns:
            (Registro, fue_creado) — tupla con el registro y un booleano
        """
        campo_id = DynamicService.obtener_identificador_principal(nombre_formulario)
        if campo_id is None:
            raise DynamicFormError(
                f'El formulario "{nombre_formulario}" no tiene un identificador principal configurado.'
            )

        nombre_campo_id = campo_id.nombre
        valor_id = valores_dict.get(nombre_campo_id, '').strip()

        if not valor_id:
            registro = DynamicService.crear(nombre_formulario, valores_dict, usuario=usuario)
            return registro, True

        registro_existente = DynamicService.buscar_por_identificador(
            nombre_formulario, valor_id
        )

        if registro_existente:
            registro = DynamicService.actualizar(registro_existente, valores_dict, usuario=usuario)
            return registro, False
        else:
            registro = DynamicService.crear(nombre_formulario, valores_dict, usuario=usuario)
            return registro, True

    # ------------------------------------------------------------------
    # ELIMINACIÓN
    # ------------------------------------------------------------------

    @staticmethod
    def eliminar(registro):
        """Elimina un registro y sus valores asociados."""
        registro.delete()
