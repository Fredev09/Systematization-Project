import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from io import BytesIO
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ======================================================================
# DIAGNÓSTICO — Helper de instrumentación temporal
# ======================================================================
_DIAG_ENABLED = True  # toggle全局 para desactivar sin borrar

def _diag_log(stage: str, start: float, detail: str = ''):
    """Registra duración de un paso. Warning si >500ms."""
    if not _DIAG_ENABLED:
        return
    elapsed_ms = (time.perf_counter() - start) * 1000
    msg = f'[DIAG] {stage}: {elapsed_ms:.1f}ms'
    if detail:
        msg += f' | {detail}'
    if elapsed_ms > 500:
        logger.warning(f'[DIAG] ⚠ {stage} EXCEDE 500ms: {elapsed_ms:.1f}ms | {detail}')
    else:
        logger.info(msg)
    return time.perf_counter()  # return new start for chaining


def _diag_start(stage: str):
    """Marca inicio de una etapa de diagnóstico."""
    if _DIAG_ENABLED:
        logger.info(f'[DIAG] >>> {stage}')
    return time.perf_counter()


# ======================================================================
# Serialización de session — helpers para objetos no JSON-serializables
# ======================================================================

def _match_results_to_dicts(match_results):
    """Convierte list[ColumnMatchResult] a list[dict] para session."""
    return [asdict(r) for r in match_results]


def _match_results_from_dicts(data):
    """Reconstruye list[ColumnMatchResult] desde list[dict] de session."""
    from .column_matching import ColumnMatchResult
    return [ColumnMatchResult(**d) for d in data]


def _summary_to_dict(summary) -> dict:
    """Convierte MappingSummary a dict serializable para session/template."""
    result = {
        'total': summary.total,
        'auto': summary.auto,
        'review': summary.review,
        'manual': summary.manual,
        'puede_saltar_mapeo': summary.puede_saltar_mapeo,
        'motivo_no_saltar': getattr(summary, 'motivo_no_saltar', []),
        'necesita_revision': summary.necesita_revision,
        'necesita_manual': summary.necesita_manual,
        'confianza_promedio': summary.confianza_promedio,
        'memoria_usada': getattr(summary, 'memoria_usada', False),
        'ai_usada': getattr(summary, 'ai_usada', False),
        'campos_obligatorios_faltantes': getattr(summary, 'campos_obligatorios_faltantes', []),
        'conflictos_presentes': getattr(summary, 'conflictos_presentes', False),
        'columnas_extra': getattr(summary, 'columnas_extra', 0),
        'audit_log': getattr(summary, 'audit_log', []),
        'columnas': [],
    }
    for cc in summary.columnas:
        if hasattr(cc, '__dataclass_fields__'):
            col_dict = {
                'column_index': cc.column_index,
                'column_name': cc.column_name,
                'matched_to': cc.matched_to,
                'confidence': cc.confidence,
                'method': cc.method,
                'category': cc.category,
                'explanation': cc.explanation,
                'suggestion': cc.suggestion,
            }
            result['columnas'].append(col_dict)
    return result

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from config.pagination import OPCIONES_POR_PAGINA, obtener_por_pagina, parametros_sin_pagina
from config.permissions import admin_required, es_administrador, rol_usuario
from .forms import FormularioForm
from .import_service import (
    MODOS_IMPORTACION,
    TIPOS_EXCLUIDOS_MAPEO,
    analizar_y_clasificar_columnas,
    analyze_workbook,
    construir_mapeo_completo,
    detectar_columnas,
    generar_excel_errores,
    generar_plantilla_excel,
    guardar_memoria_mapeo,
    importar,
    leer_excel,
    previsualizar,
    validar_estructura,
)
from .models import Campo, Formulario, ImportAudit, ImportLog, ImportSnapshot, Registro, ValorCampo
from .services import _evaluar_formula, exportar_registros_excel
from .services_dynamic import _guardar_archivo_subido
from .validators import _validar_valor_campo


def _procesar_campos_post(request, formulario):
    """Procesa los campos enviados vía POST y devuelve errores y datos."""
    nombres = request.POST.getlist('campo_nombre')
    tipos = request.POST.getlist('campo_tipo')
    obligatorios = request.POST.getlist('campo_obligatorio')
    unicos = request.POST.getlist('campo_unico')
    visibles = request.POST.getlist('campo_visible')
    ordenes = request.POST.getlist('campo_orden')
    opciones_list = request.POST.getlist('campo_opciones')
    descripciones = request.POST.getlist('campo_descripcion')
    default_values = request.POST.getlist('campo_default')
    max_lengths = request.POST.getlist('campo_max_length')
    form_destino_ids = request.POST.getlist('campo_formulario_destino')
    formulas = request.POST.getlist('campo_formula')
    identificadores_principales = request.POST.getlist('campo_identificador_principal')

    errores = []
    campos_procesados = []

    for i, nombre in enumerate(nombres):
        nombre = nombre.strip()
        if not nombre:
            continue

        tipo = tipos[i] if i < len(tipos) else 'texto'

        if tipo not in dict(Campo.TIPOS):
            errores.append(f'El tipo "{tipo}" no es válido para el campo "{nombre}".')
            continue

        es_obligatorio = (
            obligatorios[i] == 'on'
            if i < len(obligatorios)
            else False
        )
        es_unico = (
            unicos[i] == 'on'
            if i < len(unicos)
            else False
        )
        es_visible = (
            visibles[i] != 'off'
            if i < len(visibles)
            else True
        )
        orden = ordenes[i] if i < len(ordenes) else '0'
        opciones_raw = opciones_list[i] if i < len(opciones_list) else ''
        descripcion = descripciones[i] if i < len(descripciones) else ''
        default_value = default_values[i] if i < len(default_values) else ''
        max_length_raw = max_lengths[i] if i < len(max_lengths) else ''

        opciones = None
        if tipo == 'lista' and opciones_raw:
            opciones = [
                op.strip()
                for op in opciones_raw.split(',')
                if op.strip()
            ]

        # Build metadata_json
        metadata = {}
        if default_value:
            metadata['default_value'] = default_value
        if max_length_raw:
            try:
                metadata['max_length'] = int(max_length_raw)
            except (ValueError, TypeError):
                pass

        # Formulario destino para tipo 'relacion'
        formulario_destino_id = None
        if tipo == 'relacion':
            raw_id = form_destino_ids[i] if i < len(form_destino_ids) else ''
            if raw_id and raw_id.isdigit():
                formulario_destino_id = int(raw_id)

        # Fórmula para tipo 'calculado'
        formula = None
        if tipo == 'calculado':
            formula = formulas[i] if i < len(formulas) else ''
            if not formula:
                errores.append(f'El campo calculado "{nombre}" debe tener una fórmula.')

        # Identificador principal
        es_identificador = (
            identificadores_principales[i] == 'on'
            if i < len(identificadores_principales)
            else False
        )

        campos_procesados.append({
            'nombre': nombre,
            'tipo': tipo,
            'obligatorio': es_obligatorio,
            'unico': es_unico,
            'visible': es_visible,
            'orden': int(orden) if orden.isdigit() else 0,
            'opciones': opciones,
            'descripcion': descripcion,
            'metadata': metadata if metadata else None,
            'formulario_destino_id': formulario_destino_id,
            'formula': formula,
            'identificador_principal': es_identificador,
        })

    return campos_procesados, errores


def _sincronizar_campos(formulario, campos_procesados):
    """
    Sincroniza los campos de un formulario sin eliminar datos existentes:
    - Crea campos nuevos.
    - Actualiza campos existentes (por nombre).
    - Marca como inactivos (activo=False) los campos que ya no están en la lista.
    - Reactiva campos que vuelven a aparecer.
    
    Soporta todos los campos nuevos (v2.0+): descripcion, visible, unico, metadata_json.
    """
    nombres_procesados = {c['nombre'] for c in campos_procesados}
    campos_existentes = {c.nombre: c for c in formulario.campos.all()}

    for datos in campos_procesados:
        nombre = datos['nombre']
        if nombre in campos_existentes:
            # Actualizar campo existente
            campo = campos_existentes[nombre]
            campo.tipo = datos['tipo']
            campo.obligatorio = datos['obligatorio']
            campo.orden = datos['orden']
            campo.opciones = datos['opciones']
            campo.activo = True  # Reactivar si estaba inactivo
            update_fields = ['tipo', 'obligatorio', 'orden', 'opciones', 'activo']

            # Nuevos campos (v2.0)
            if 'unico' in datos:
                campo.unico = datos['unico']
                update_fields.append('unico')
            if 'visible' in datos:
                campo.visible = datos['visible']
                update_fields.append('visible')
            if 'descripcion' in datos:
                campo.descripcion = datos['descripcion']
                update_fields.append('descripcion')
            if 'metadata' in datos and datos['metadata']:
                campo.metadata_json = datos['metadata']
                update_fields.append('metadata_json')

            if 'formulario_destino_id' in datos:
                campo.formulario_destino_id = datos['formulario_destino_id']
                update_fields.append('formulario_destino_id')
            if 'formula' in datos:
                campo.formula = datos.get('formula')
                update_fields.append('formula')

            if datos.get('identificador_principal'):
                campo.identificador_principal = True
                update_fields.append('identificador_principal')

            campo.save(update_fields=update_fields)
        else:
            # Crear campo nuevo
            kwargs = {
                'formulario': formulario,
                'nombre': nombre,
                'tipo': datos['tipo'],
                'obligatorio': datos['obligatorio'],
                'orden': datos['orden'],
                'opciones': datos['opciones'],
            }
            # Nuevos campos (v2.0)
            if 'unico' in datos:
                kwargs['unico'] = datos['unico']
            if 'visible' in datos:
                kwargs['visible'] = datos['visible']
            if 'descripcion' in datos:
                kwargs['descripcion'] = datos.get('descripcion', '')
            if 'metadata' in datos and datos['metadata']:
                kwargs['metadata_json'] = datos['metadata']
            if 'formulario_destino_id' in datos:
                kwargs['formulario_destino_id'] = datos['formulario_destino_id']
            if 'formula' in datos:
                kwargs['formula'] = datos.get('formula')
            if datos.get('identificador_principal'):
                kwargs['identificador_principal'] = True

            Campo.objects.create(**kwargs)

    # Archivar campos que ya no están en la lista
    for nombre, campo in campos_existentes.items():
        if nombre not in nombres_procesados and campo.activo:
            campo.activo = False
            campo.save(update_fields=['activo'])


# ---------------------------------------------------------------------------
# Helpers para tipo 'relacion' y 'calculado'
# ---------------------------------------------------------------------------

def _obtener_opciones_relacion(campo):
    """Obtiene las opciones para un select de tipo 'relacion'.
    Retorna [(registro_id, display_text), ...]"""
    if not campo.formulario_destino_id:
        return []
    registros = Registro.objects.filter(
        formulario_id=campo.formulario_destino_id
    ).order_by('-fecha_creacion')[:500]  # límite de seguridad
    primer_campo = Campo.objects.filter(
        formulario_id=campo.formulario_destino_id, activo=True
    ).order_by('orden').first()

    opciones = []
    # Cargar valores del primer campo en lote
    valores_map = {}
    if primer_campo:
        vcs = ValorCampo.objects.filter(
            registro__in=registros,
            campo=primer_campo
        ).values_list('registro_id', 'valor')
        for rid, val in vcs:
            valores_map[rid] = val

    for r in registros:
        display = f"#{r.id}"
        val = valores_map.get(r.id)
        if val:
            display += f" - {val[:80]}"
        opciones.append((r.id, display))
    return opciones


def _resolver_valores_relacion(campos, valores_map):
    """Resuelve IDs de registros en campos tipo 'relacion' a textos legibles.
    Retorna {registro_id_original: "texto_legible"}
    """
    referencias = defaultdict(set)  # {formulario_id: {registro_id}}

    for campo in campos:
        if campo.tipo == 'relacion' and campo.formulario_destino_id:
            for vc_valor in valores_map.values():
                raw = vc_valor.get(campo.id, '').strip()
                if raw and raw.isdigit():
                    referencias[campo.formulario_destino_id].add(int(raw))

    resolved = {}  # {registro_id: "display_text"}
    for form_id, reg_ids in referencias.items():
        if not reg_ids:
            continue
        refs = Registro.objects.filter(id__in=list(reg_ids), formulario_id=form_id)
        primer_campo = Campo.objects.filter(
            formulario_id=form_id, activo=True
        ).order_by('orden').first()

        # Cargar valores del primer campo en lote
        nombres_valores = {}
        if primer_campo:
            vcs = ValorCampo.objects.filter(
                registro__in=refs,
                campo=primer_campo
            ).values_list('registro_id', 'valor')
            for rid, val in vcs:
                nombres_valores[rid] = val

        for ref in refs:
            display = f"#{ref.id}"
            val = nombres_valores.get(ref.id)
            if val:
                display += f" - {val[:80]}"
            resolved[ref.id] = display

    return resolved


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------

@login_required(login_url='login')
@admin_required
def listar_formularios(request):
    """Vista para administradores que muestra todos los formularios en tarjetas."""
    formularios = Formulario.objects.all().order_by('-fecha_creacion')

    for f in formularios:
        f.total_campos = f.campos.filter(activo=True).count()
        f.total_registros = f.registros.count()

    return render(request, 'dynamic_forms/lista_formularios.html', {
        'formularios': formularios,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def crear_formulario(request):
    """Vista con formset dinámico para crear formulario y sus campos."""
    if request.method == 'POST':
        form = FormularioForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                formulario = form.save(commit=False)
                formulario.creado_por = request.user
                formulario.save()

                campos_procesados, errores = _procesar_campos_post(request, formulario)

                if not campos_procesados:
                    formulario.delete()
                    messages.error(
                        request,
                        'Debes agregar al menos un campo al formulario.'
                    )
                    return render(request, 'dynamic_forms/crear_formulario.html', {
                        'form': form,
                        'es_admin': es_administrador(request.user),
                        'rol_usuario': rol_usuario(request.user),
                    })

                # Validar nombres duplicados
                nombres_vistos = set()
                for datos in campos_procesados:
                    if datos['nombre'] in nombres_vistos:
                        errores.append(f'El campo "{datos["nombre"]}" está duplicado.')
                    nombres_vistos.add(datos['nombre'])

            if errores:
                for error in errores:
                    messages.warning(request, error)

                _sincronizar_campos(formulario, campos_procesados)

            # Auto-crear identificador principal si se solicitó
            if form.cleaned_data.get('generar_identificador'):
                nombre_id = form.cleaned_data.get('nombre_identificador', 'Código').strip()
                if not nombre_id:
                    nombre_id = 'Código'
                # Verificar si ya existe un campo con ese nombre
                campo_existente = formulario.campos.filter(nombre=nombre_id).first()
                if not campo_existente:
                    Campo.objects.create(
                        formulario=formulario,
                        nombre=nombre_id,
                        tipo='texto',
                        obligatorio=True,
                        unico=True,
                        identificador_principal=True,
                        orden=-1,  # Aparecer primero
                    )

            messages.success(
                request,
                f'Formulario "{formulario.nombre}" creado correctamente.'
            )
            return redirect('dynamic_forms:listar_formularios')
        else:
            messages.error(
                request,
                'No se pudo crear el formulario. Revisa los datos ingresados.'
            )
    else:
        form = FormularioForm()

    return render(request, 'dynamic_forms/crear_formulario.html', {
        'form': form,
        'formularios_disponibles': Formulario.objects.filter(activo=True),
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def editar_formulario(request, formulario_id):
    """Editar formulario y sus campos SIN eliminar datos existentes."""
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )

    if request.method == 'POST':
        form = FormularioForm(request.POST, instance=formulario)

        if form.is_valid():
            with transaction.atomic():
                formulario = form.save()

                campos_procesados, errores = _procesar_campos_post(request, formulario)
                _sincronizar_campos(formulario, campos_procesados)

                if errores:
                    for error in errores:
                        messages.warning(request, error)

            messages.success(
                request,
                f'Formulario "{formulario.nombre}" actualizado correctamente.'
            )
            return redirect('dynamic_forms:listar_formularios')
        else:
            messages.error(
                request,
                'No se pudo actualizar el formulario. Revisa los datos ingresados.'
            )
    else:
        form = FormularioForm(instance=formulario)

    return render(request, 'dynamic_forms/editar_formulario.html', {
        'form': form,
        'formulario': formulario,
        'campos': formulario.campos.filter(activo=True),
        'formularios_disponibles': Formulario.objects.filter(activo=True).exclude(id=formulario.id),
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def eliminar_formulario(request, formulario_id):
    """Eliminar formulario con confirmación."""
    formulario = get_object_or_404(Formulario, id=formulario_id)

    if request.method == 'POST':
        confirmar = request.POST.get('confirmar')
        if confirmar == 'si':
            nombre = formulario.nombre
            formulario.delete()
            messages.success(
                request,
                f'Formulario "{nombre}" eliminado correctamente.'
            )
            return redirect('dynamic_forms:listar_formularios')
        else:
            messages.error(
                request,
                'Debes confirmar la eliminación para continuar.'
            )

    return render(request, 'dynamic_forms/confirmar_eliminar.html', {
        'formulario': formulario,
        'total_registros': formulario.registros.count(),
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def gestionar_campos(request, formulario_id):
    """Vista para administrar campos de un formulario específico SIN eliminar datos."""
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )

    if request.method == 'POST':
        with transaction.atomic():
            campos_procesados, errores = _procesar_campos_post(request, formulario)
            _sincronizar_campos(formulario, campos_procesados)

            if errores:
                for error in errores:
                    messages.warning(request, error)

        messages.success(
            request,
            f'Campos de "{formulario.nombre}" actualizados correctamente.'
        )
        return redirect('dynamic_forms:listar_formularios')

    return render(request, 'dynamic_forms/gestionar_campos.html', {
        'formulario': formulario,
        'campos': formulario.campos.filter(activo=True),
        'formularios_disponibles': Formulario.objects.filter(activo=True).exclude(id=formulario.id),
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


def llenar_formulario(request, formulario_id):
    """Vista que renderiza el formulario dinámico y guarda registros.
    
    Si el formulario tiene hooks configurados, requiere autenticación
    y permisos de administrador por seguridad.
    
    Soporta hooks post-creación y bloqueo pesimista (select_for_update)
    para formularios que lo requieran (ej: Ventas, Inventario).
    """
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )

    # Seguridad: formularios con hooks requieren autenticación + admin
    if formulario.hook_post_crear or formulario.hook_post_actualizar:
        if not request.user.is_authenticated:
            messages.error(request, 'Debes iniciar sesión para acceder a este formulario.')
            return redirect('login')
        if not es_administrador(request.user):
            messages.error(request, 'No tienes permisos para acceder a esta sección.')
            return redirect('dashboard')

    if not formulario.activo:
        return render(request, 'dynamic_forms/llenar_formulario.html', {
            'formulario': formulario,
            'formulario_inactivo': True,
            'es_admin': es_administrador(request.user) if request.user.is_authenticated else False,
            'rol_usuario': rol_usuario(request.user) if request.user.is_authenticated else '',
        })

    campos = formulario.campos.filter(activo=True)

    # Cargar opciones para campos tipo 'relacion'
    opciones_relacion = {}
    for c in campos:
        if c.tipo == 'relacion':
            opciones_relacion[c.id] = _obtener_opciones_relacion(c)

    if request.method == 'POST':
        # ------------------------------------------------------------------
        # Validar unicidad de campos marcados como 'unico' antes de crear
        # ------------------------------------------------------------------
        errores_validacion = []
        for campo in campos:
            if campo.unico:
                valor_raw = request.POST.get(f'campo_{campo.id}', '').strip()
                if valor_raw:
                    from .services_dynamic import DynamicService, ValorUnicoError
                    try:
                        DynamicService.validar_unicidad(formulario, campo.nombre, valor_raw)
                    except ValorUnicoError as e:
                        errores_validacion.extend(e.errores)

        if errores_validacion:
            return render(request, 'dynamic_forms/llenar_formulario.html', {
                'formulario': formulario,
                'campos': campos,
                'opciones_relacion': opciones_relacion,
                'errores': errores_validacion,
                'es_admin': es_administrador(request.user) if request.user.is_authenticated else False,
                'rol_usuario': rol_usuario(request.user) if request.user.is_authenticated else '',
            })

        with transaction.atomic():
            # ------------------------------------------------------------------
            # Bloqueo pesimista: si el formulario tiene hooks, bloqueamos
            # el formulario para evitar condiciones de carrera (ej: stock)
            # ------------------------------------------------------------------
            if formulario.hook_post_crear or formulario.hook_post_actualizar:
                Formulario.objects.select_for_update().filter(id=formulario.id).exists()

            registro = Registro.objects.create(
                formulario=formulario,
                usuario=request.user if request.user.is_authenticated else None
            )

            # Primera pasada: recolectar todos los valores para poder evaluar fórmulas
            valores_guardados = {}  # {campo_id: valor}
            errores = []

            for campo in campos:
                if campo.tipo in Campo.TIPOS_ARCHIVO:
                    archivo = request.FILES.get(f'campo_{campo.id}')
                    if campo.obligatorio and not archivo:
                        errores.append(f'El campo "{campo.nombre}" es obligatorio.')
                        continue
                    if archivo:
                        valor_raw = _guardar_archivo_subido(
                            archivo, campo.nombre, formulario.nombre
                        )
                    else:
                        continue
                elif campo.tipo == 'calculado':
                    continue  # Se calcula en la segunda pasada
                elif campo.tipo == 'relacion':
                    valor_raw = request.POST.get(f'campo_{campo.id}', '').strip()
                    if campo.obligatorio and not valor_raw:
                        errores.append(f'El campo "{campo.nombre}" es obligatorio.')
                        continue
                    if not valor_raw:
                        continue
                    valor_limpio, error = _validar_valor_campo(campo, valor_raw)
                    if error:
                        errores.append(error)
                        continue
                    valor_raw = valor_limpio
                else:
                    valor_raw = request.POST.get(f'campo_{campo.id}', '').strip()
                    if campo.obligatorio and not valor_raw:
                        errores.append(f'El campo "{campo.nombre}" es obligatorio.')
                        continue
                    if not valor_raw:
                        continue
                    valor_limpio, error = _validar_valor_campo(campo, valor_raw)
                    if error:
                        errores.append(error)
                        continue
                    valor_raw = valor_limpio

                if errores:
                    break

                ValorCampo.objects.create(
                    registro=registro,
                    campo=campo,
                    valor=valor_raw,
                )
                valores_guardados[campo.id] = valor_raw

            if not errores:
                # Segunda pasada: campos calculados
                # Se actualiza valores_por_nombre en cada iteración para permitir
                # encadenamiento (ej: subtotal → total = subtotal - descuento)
                valores_por_nombre = {}
                for campo in campos:
                    v = valores_guardados.get(campo.id, '')
                    if campo.tipo == 'numero':
                        try:
                            valores_por_nombre[campo.nombre] = float(str(v).replace(',', '.'))
                        except (ValueError, TypeError):
                            valores_por_nombre[campo.nombre] = 0
                    else:
                        valores_por_nombre[campo.nombre] = v

                for campo in campos:
                    if campo.tipo == 'calculado':
                        resultado = _evaluar_formula(campo.formula, valores_por_nombre)
                        ValorCampo.objects.create(
                            registro=registro,
                            campo=campo,
                            valor=resultado,
                        )
                        valores_por_nombre[campo.nombre] = resultado

            if errores:
                transaction.set_rollback(True)
                return render(request, 'dynamic_forms/llenar_formulario.html', {
                    'formulario': formulario,
                    'campos': campos,
                    'opciones_relacion': opciones_relacion,
                    'errores': errores,
                    'es_admin': es_administrador(request.user) if request.user.is_authenticated else False,
                    'rol_usuario': rol_usuario(request.user) if request.user.is_authenticated else '',
                })

            # ------------------------------------------------------------------
            # Ejecutar hook post-crear si está definido
            # ------------------------------------------------------------------
            if formulario.hook_post_crear:
                from .models import _importar_funcion
                fn = _importar_funcion(formulario.hook_post_crear)
                if fn:
                    try:
                        fn(registro)
                    except Exception as e:
                        logger.exception(f'Hook post-crear falló en #{registro.id}: {e}')
                        transaction.set_rollback(True)
                        return render(request, 'dynamic_forms/llenar_formulario.html', {
                            'formulario': formulario,
                            'campos': campos,
                            'opciones_relacion': opciones_relacion,
                            'errores': [f'Error al procesar: {e}'],
                            'es_admin': es_administrador(request.user) if request.user.is_authenticated else False,
                            'rol_usuario': rol_usuario(request.user) if request.user.is_authenticated else '',
                        })

        messages.success(
            request,
            'Registro guardado correctamente.'
        )
        return redirect('dynamic_forms:llenar_formulario', formulario_id=formulario.id)

    return render(request, 'dynamic_forms/llenar_formulario.html', {
        'formulario': formulario,
        'campos': campos,
        'opciones_relacion': opciones_relacion,
        'es_admin': es_administrador(request.user) if request.user.is_authenticated else False,
        'rol_usuario': rol_usuario(request.user) if request.user.is_authenticated else '',
    })


@login_required(login_url='login')
@admin_required
def ver_registros(request, formulario_id):
    """Lista todos los registros de un formulario con paginación."""
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )
    campos = formulario.campos.filter(activo=True)

    registros = Registro.objects.filter(
        formulario=formulario
    ).select_related('usuario').order_by('-fecha_creacion')

    per_page, per_page_int = obtener_por_pagina(request)
    paginator = Paginator(registros, per_page_int)
    pagina = request.GET.get('page')
    registros_pagina = paginator.get_page(pagina)
    query_params = parametros_sin_pagina(request, ['page'])

    # Cargar valores para los registros de esta página
    valores_qs = ValorCampo.objects.filter(
        registro__in=registros_pagina
    ).select_related('campo')

    valores_map = {}
    for vc in valores_qs:
        if vc.registro_id not in valores_map:
            valores_map[vc.registro_id] = {}
        valores_map[vc.registro_id][vc.campo_id] = vc.valor

    # Resolver valores de campos tipo 'relacion'
    relacion_resuelto = _resolver_valores_relacion(campos, valores_map)

    # Reemplazar IDs por textos legibles en valores_map
    for reg_id, vals in valores_map.items():
        for campo in campos:
            if campo.tipo == 'relacion':
                raw = vals.get(campo.id, '')
                if raw and raw.isdigit():
                    ref_id = int(raw)
                    display = relacion_resuelto.get(ref_id)
                    if display:
                        vals[campo.id] = display

    # Identificar campo identificador principal
    campo_identificador = campos.filter(identificador_principal=True).first()

    return render(request, 'dynamic_forms/ver_registros.html', {
        'formulario': formulario,
        'campos': campos,
        'campo_identificador': campo_identificador,
        'registros': registros_pagina,
        'valores_map': valores_map,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
        'query_params': query_params,
        'per_page': per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })


@login_required(login_url='login')
@admin_required
def editar_registro(request, formulario_id, registro_id):
    """Edita un registro existente de un formulario dinámico."""
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )
    registro = get_object_or_404(
        Registro.objects.prefetch_related('valores__campo'),
        id=registro_id,
        formulario=formulario
    )
    campos = formulario.campos.filter(activo=True)

    # Cargar valores actuales
    valores_actuales = {}
    for vc in registro.valores.all():
        valores_actuales[vc.campo_id] = vc.valor

    # Cargar opciones para campos tipo 'relacion'
    opciones_relacion = {}
    for c in campos:
        if c.tipo == 'relacion':
            opciones_relacion[c.id] = _obtener_opciones_relacion(c)

    if request.method == 'POST':
        with transaction.atomic():
            errores = []

            # Actualizar fecha de modificación
            registro.save(update_fields=['fecha_actualizacion'])

            # Recolectar valores actualizados (sin calculados)
            valores_actualizados = {}
            for campo in campos:
                if campo.tipo in Campo.TIPOS_ARCHIVO:
                    archivo = request.FILES.get(f'campo_{campo.id}')
                    if archivo:
                        valor_raw = _guardar_archivo_subido(
                            archivo, campo.nombre, formulario.nombre
                        )
                    else:
                        valor_post = request.POST.get(f'campo_{campo.id}', '').strip()
                        if valor_post:
                            valor_raw = valor_post
                        else:
                            if campo.obligatorio and not valores_actuales.get(campo.id):
                                errores.append(f'El campo "{campo.nombre}" es obligatorio.')
                            continue
                elif campo.tipo == 'calculado':
                    continue  # Se recalcula al final
                elif campo.tipo == 'relacion':
                    valor_raw = request.POST.get(f'campo_{campo.id}', '').strip()
                    if campo.obligatorio and not valor_raw:
                        errores.append(f'El campo "{campo.nombre}" es obligatorio.')
                        continue
                    if not valor_raw:
                        ValorCampo.objects.filter(registro=registro, campo=campo).delete()
                        continue
                    valor_limpio, error = _validar_valor_campo(campo, valor_raw)
                    if error:
                        errores.append(error)
                        continue
                    valor_raw = valor_limpio
                else:
                    valor_raw = request.POST.get(f'campo_{campo.id}', '').strip()
                    if campo.obligatorio and not valor_raw:
                        errores.append(f'El campo "{campo.nombre}" es obligatorio.')
                        continue
                    if not valor_raw:
                        ValorCampo.objects.filter(registro=registro, campo=campo).delete()
                        continue
                    valor_limpio, error = _validar_valor_campo(campo, valor_raw)
                    if error:
                        errores.append(error)
                        continue
                    valor_raw = valor_limpio

                if errores:
                    break

                ValorCampo.objects.update_or_create(
                    registro=registro,
                    campo=campo,
                    defaults={'valor': valor_raw},
                )
                valores_actualizados[campo.id] = valor_raw

            if not errores:
                # Recalcular campos calculados (con encadenamiento)
                valores_por_nombre = {}
                for campo in campos:
                    v = valores_actualizados.get(campo.id, valores_actuales.get(campo.id, ''))
                    if campo.tipo == 'numero':
                        try:
                            valores_por_nombre[campo.nombre] = float(str(v).replace(',', '.'))
                        except (ValueError, TypeError):
                            valores_por_nombre[campo.nombre] = 0
                    else:
                        valores_por_nombre[campo.nombre] = v

                for campo in campos:
                    if campo.tipo == 'calculado':
                        resultado = _evaluar_formula(campo.formula, valores_por_nombre)
                        ValorCampo.objects.update_or_create(
                            registro=registro,
                            campo=campo,
                            defaults={'valor': resultado},
                        )
                        valores_por_nombre[campo.nombre] = resultado

            if errores:
                transaction.set_rollback(True)
                return render(request, 'dynamic_forms/editar_registro.html', {
                    'formulario': formulario,
                    'registro': registro,
                    'campos': campos,
                    'valores_actuales': valores_actuales,
                    'opciones_relacion': opciones_relacion,
                    'errores': errores,
                    'es_admin': es_administrador(request.user),
                    'rol_usuario': rol_usuario(request.user),
                })

        messages.success(
            request,
            'Registro actualizado correctamente.'
        )
        return redirect('dynamic_forms:ver_registros', formulario_id=formulario.id)

    return render(request, 'dynamic_forms/editar_registro.html', {
        'formulario': formulario,
        'registro': registro,
        'campos': campos,
        'valores_actuales': valores_actuales,
        'opciones_relacion': opciones_relacion,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def importar_excel(request, formulario_id):
    """
    Vista multi-paso para importar registros desde Excel.

    Paso 1: GET → formulario de subida
    Paso 2: POST (subir) → analizar Excel, detectar hoja/header/datos/matching
    Paso 3: POST (mapear) → confirmar mapeo + seleccionar modo
    Paso 4: POST (preview) → validar estructura + preview
    Paso 5: POST (importar) → ejecutar importación según modo elegido
    """
    _t0 = time.perf_counter()
    logger.info(
        f'[DIAG] ========== IMPORTAR_EXCEL ENTRY ==========\n'
        f'[DIAG] Timestamp: {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
        f'[DIAG] formulario_id: {formulario_id}\n'
        f'[DIAG] request.method: {request.method}\n'
        f'[DIAG] request.POST keys: {list(request.POST.keys())}\n'
        f'[DIAG] request.FILES keys: {list(request.FILES.keys())}\n'
        f'[DIAG] CONTENT_LENGTH: {request.META.get("CONTENT_LENGTH", "N/A")}'
    )

    _t_frm = _diag_start('get_object_or_404 + campos_activos')
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )
    campos_activos = formulario.campos.filter(activo=True).order_by('orden')
    _diag_log('get_object_or_404 + campos_activos', _t_frm, f'formulario={formulario.nombre}, campos_count={campos_activos.count()}')

    paso = request.POST.get('paso', 'subir')
    logger.info(f'[DIAG] paso detectado: {paso}')
    logger.info(f'[DIAG] tiempo_acumulado_antes_paso: {(time.perf_counter() - _t0) * 1000:.1f}ms')

    # --- Paso 5: Ejecutar importación ---
    if paso == 'importar':
        import_data = request.session.pop('import_data', None)
        mapping_data = request.session.pop('mapping_data', None)
        modo = request.session.pop('modo_importacion', 'crear')
        if not import_data or not mapping_data:
            messages.error(request, 'La sesión de importación ha expirado. Sube el archivo nuevamente.')
            return redirect('dynamic_forms:importar_excel', formulario_id=formulario.id)

        encabezados = import_data['encabezados']
        filas = import_data['filas']
        mapeo_idx = {int(k): v for k, v in mapping_data.items()}

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        filas_validas = [r for r in preview if r['valida']]

        if not filas_validas:
            messages.warning(request, 'No hay filas válidas para importar.')
            return redirect('dynamic_forms:importar_excel', formulario_id=formulario.id)

        # Ejecutar dry run si modo == 'validar'
        if modo == 'validar':
            resultado = {
                'total': len(filas_validas),
                'creados': 0,
                'actualizados': 0,
                'ignorados': len(filas_validas),
                'errores': [],
                'tiempo_seg': 0.0,
                'modo': 'validar',
            }
            messages.success(request, 'Dry Run completado. Ningún registro fue modificado.')
        else:
            resultado = importar(
                formulario, filas_validas,
                usuario=request.user, modo=modo, mapeo=mapeo_idx
            )
            if resultado['errores']:
                request.session['ultimos_errores'] = resultado['errores']
                request.session['formulario_nombre_errores'] = formulario.nombre

            # Guardar mapeo en memoria persistente para futuras importaciones
            if resultado['creados'] > 0 or resultado['actualizados'] > 0:
                guardar_memoria_mapeo(formulario, encabezados, mapeo_idx)

        # Limpiar datos de sesión residuales (FASE 9)
        for key in ['match_results', 'analysis_meta', 'calidad', 'conflictos_globales', 'tipo_campos', 'mapeo_auto_summary', 'mapeo_saltado']:
            request.session.pop(key, None)

        return render(request, 'dynamic_forms/importar_excel.html', {
            'formulario': formulario,
            'paso': 'resultado',
            'resultado': resultado,
            'es_admin': es_administrador(request.user),
            'rol_usuario': rol_usuario(request.user),
        })

    # --- Paso 4: Validar estructura + previsualizar ---
    if paso == 'preview':
        import_data = request.session.get('import_data')
        mapping_data = request.session.get('mapping_data')
        if not import_data or not mapping_data:
            messages.error(request, 'La sesión de importación ha expirado. Sube el archivo nuevamente.')
            return redirect('dynamic_forms:importar_excel', formulario_id=formulario.id)

        encabezados = import_data['encabezados']
        filas = import_data['filas']
        match_results_raw = request.session.get('match_results')
        match_results = _match_results_from_dicts(match_results_raw) if match_results_raw else []
        mapeo_idx = {int(k): v for k, v in mapping_data.items()}
        modo = request.POST.get('modo_importacion', 'crear')
        mapeo_saltado = request.session.pop('mapeo_saltado', False)

        if modo not in MODOS_IMPORTACION:
            messages.error(request, 'Modo de importación inválido.')
            return redirect('dynamic_forms:importar_excel', formulario_id=formulario.id)

        # Guardar modo en sesión
        request.session['modo_importacion'] = modo

        # Validación avanzada de estructura
        validacion = validar_estructura(
            formulario, encabezados, filas, mapeo_idx, match_results
        )

        if not validacion['valido']:
            for error in validacion['errores']:
                messages.error(request, error)
            # Volver al paso de mapeo
            encabezados_con_idx = [(idx, nombre) for idx, nombre in enumerate(encabezados)]
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'mapeo',
                'encabezados': encabezados,
                'encabezados_con_idx': encabezados_con_idx,
                'campos_activos': campos_activos,
                'mapeo_idx': mapeo_idx,
                'total_filas': len(filas),
                'modo_actual': modo,
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })

        # Preview de validación de filas
        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        validas = [r for r in preview if r['valida']]
        con_errores = [r for r in preview if not r['valida']]

        request.session['import_data'] = import_data
        request.session['mapping_data'] = mapping_data
        analysis_meta = request.session.get('analysis_meta')
        calidad = request.session.get('calidad', {})
        conflictos_globales = request.session.get('conflictos_globales', [])
        tipo_campos = request.session.get('tipo_campos', {})
        auto_summary = request.session.pop('mapeo_auto_summary', None)

        modo_msg = MODOS_IMPORTACION.get(modo, modo)

        return render(request, 'dynamic_forms/importar_excel.html', {
            'formulario': formulario,
            'paso': 'preview',
            'preview': preview,
            'validas': validas,
            'con_errores': con_errores,
            'total_filas': len(filas),
            'validacion': validacion,
            'modo_actual': modo,
            'modo_msg': modo_msg,
            'es_admin': es_administrador(request.user),
            'rol_usuario': rol_usuario(request.user),
            'analysis_meta': analysis_meta,
            'calidad': calidad,
            'conflictos_globales': conflictos_globales,
            'tipo_campos': tipo_campos,
            'auto_summary': auto_summary,
            'mapeo_saltado': mapeo_saltado,
        })

    # --- Paso 3: Confirmar mapeo + seleccionar modo ---
    if paso == 'mapear':
        import_data = request.session.get('import_data')
        if not import_data:
            messages.error(request, 'La sesión de importación ha expirado. Sube el archivo nuevamente.')
            return redirect('dynamic_forms:importar_excel', formulario_id=formulario.id)

        encabezados = import_data['encabezados']
        filas = import_data['filas']

        # Recoger mapeo del formulario
        mapeo_usuario = {}
        for key, value in request.POST.items():
            if key.startswith('mapeo_'):
                col_idx = key.replace('mapeo_', '')
                if col_idx.isdigit() and value:
                    mapeo_usuario[int(col_idx)] = value

        modo = request.POST.get('modo_importacion', 'crear')
        if modo not in MODOS_IMPORTACION:
            messages.error(request, 'Modo de importación inválido.')
            return redirect('dynamic_forms:importar_excel', formulario_id=formulario.id)

        match_results_raw = request.session.get('match_results')
        # Recalcular match_results si el usuario hizo cambios manuales
        if mapeo_usuario and match_results_raw:
            match_results_objects = _match_results_from_dicts(match_results_raw)
            for r in match_results_objects:
                if r.column_index in mapeo_usuario:
                    r.matched_to = mapeo_usuario[r.column_index]
                    r.method = 'manual'
                    r.confidence = 1.0
            request.session['match_results'] = _match_results_to_dicts(match_results_objects)

        mapeo_idx, sin_mapear = construir_mapeo_completo(encabezados, formulario, mapeo_usuario)

        # Validar campos obligatorios mapeados
        errores_mapeo = []
        for campo in campos_activos:
            if campo.obligatorio and campo.tipo not in TIPOS_EXCLUIDOS_MAPEO:
                if campo.nombre not in mapeo_idx.values():
                    errores_mapeo.append(
                        f'El campo obligatorio "{campo.nombre}" no está mapeado a ninguna columna.'
                    )

        if errores_mapeo:
            for err in errores_mapeo:
                messages.error(request, err)
            encabezados_con_idx = [(idx, nombre) for idx, nombre in enumerate(encabezados)]
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'mapeo',
                'encabezados': encabezados,
                'encabezados_con_idx': encabezados_con_idx,
                'campos_activos': campos_activos,
                'mapeo_idx': mapeo_idx,
                'total_filas': len(filas),
                'modo_actual': modo,
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })

        # Guardar mapeo en sesión
        request.session['mapping_data'] = {str(k): v for k, v in mapeo_idx.items()}

        # Pasar al preview
        request.session['modo_importacion'] = modo

        return redirect('dynamic_forms:importar_excel', formulario_id=formulario.id)

    # --- Paso 2: Subir y analizar archivo ---
    if request.method == 'POST' and paso == 'subir':
        _t_subir = time.perf_counter()
        logger.info(f'[DIAG] >>> PASO_SUBIR inicio | tiempo_acumulado: {(_t_subir - _t0) * 1000:.1f}ms')

        archivo = request.FILES.get('archivo_excel')
        if not archivo:
            logger.warning('[DIAG] PASO_SUBIR: No file uploaded')
            messages.error(request, 'Debes seleccionar un archivo Excel.')
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'subir',
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })

        logger.info(f'[DIAG] File received: name={archivo.name}, size={archivo.size}, content_type={archivo.content_type}')

        # Validación de seguridad (FASE 5)
        _t_fileval = _diag_start('_validar_archivo_importacion')
        try:
            from .import_service import _validar_archivo_importacion, _limitar_filas
            _validar_archivo_importacion(archivo)
        except ValueError as e:
            _diag_log('_validar_archivo_importacion (FAILED)', _t_fileval, str(e))
            messages.error(request, str(e))
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'subir',
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })
        _diag_log('_validar_archivo_importacion', _t_fileval, 'OK')

        # Análisis mejorado: auto-detección completa
        _t_awb = _diag_start('analyze_workbook')
        try:
            analysis = analyze_workbook(archivo, formulario)
        except ValueError as e:
            _diag_log('analyze_workbook (FAILED)', _t_awb, str(e))
            messages.error(request, str(e))
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'subir',
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })
        _diag_log('analyze_workbook', _t_awb,
                   f'sheet={analysis.get("sheet_name","?")}, '
                   f'columns={len(analysis.get("encabezados",[]))}, '
                   f'raw_rows={analysis.get("total_filas","?")}, '
                   f'header_row={analysis.get("header_row","?")}, '
                   f'data_start_row={analysis.get("data_start_row","?")}')

        _t_post = _diag_start('post_analysis (mapeo + session)')

        encabezados = analysis['encabezados']
        filas = _limitar_filas(analysis['filas'])
        match_results = analysis['match_results']

        logger.info(f'[DIAG] Post-analysis: encabezados={len(encabezados)}, filas={len(filas)}, match_results={len(match_results)}')

        # =============================================================
        # ORQUESTACIÓN COMPLETA: ColumnMatcher + MappingMemory +
        #                       AIMatcher + AutoMappingAnalyzer
        # =============================================================
        _t_auto = _diag_start('analizar_y_clasificar_columnas')
        resultado_auto = analizar_y_clasificar_columnas(
            formulario=formulario,
            encabezados=encabezados,
            campos_activos=campos_activos,
        )
        summary = resultado_auto['summary']
        mapeo_idx = resultado_auto['mapeo_idx']
        sin_mapear = resultado_auto['sin_mapear']
        _diag_log('analizar_y_clasificar_columnas', _t_auto,
                   f'Auto={summary.auto}, Review={summary.review}, '
                   f'Manual={summary.manual}, puede_saltar={summary.puede_saltar_mapeo}, '
                   f'memoria={summary.memoria_usada}, ai={summary.ai_usada}')

        # Guardar en sesión
        _t_sess = _diag_start('session_write')
        request.session['import_data'] = {
            'encabezados': encabezados,
            'filas': filas,
        }
        request.session['analysis_meta'] = {
            'sheet_name': analysis['sheet_name'],
            'total_sheets': analysis['total_sheets'],
            'all_sheets_scores': analysis.get('all_sheets_scores', {}),
            'header_row': analysis['header_row'],
            'header_score': analysis['header_score'],
            'data_start_row': analysis.get('data_start_row', analysis['header_row'] + 1),
            'confianza_global': analysis['confianza_global'],
        }
        request.session['match_results'] = _match_results_to_dicts(match_results)
        request.session['calidad'] = analysis.get('calidad', {})
        request.session['conflictos_globales'] = analysis.get('conflictos_globales', [])
        request.session['mapeo_auto_summary'] = _summary_to_dict(summary)

        # Mapa de tipos de campo para normalización (FASE 5)
        tipo_campos = {c.nombre: c.tipo for c in campos_activos}
        request.session['tipo_campos'] = tipo_campos
        _diag_log('session_write', _t_sess, '6 keys written')

        encabezados_con_idx = [(idx, nombre) for idx, nombre in enumerate(encabezados)]

        _diag_log('post_analysis (mapeo + session)', _t_post)

        # =============================================================
        # DECISIÓN UNIFICADA: ¿Saltar pantalla de mapeo?
        # Llamar a decidir_accion() evalúa TODAS las condiciones:
        #   - Todos los campos obligatorios deben estar mapeados
        #   - Sin conflictos entre columnas
        #   - Confianza promedio >= threshold (92%)
        #   - Ninguna columna 'manual' sin resolver
        # Si todo está bien → salta a preview (aunque haya columnas
        # opcionales del Excel sin correspondencia en el formulario).
        # La decisión se renderiza EN LINEA (sin redirect) para evitar
        # que GET muestre el formulario de subida.
        # =============================================================
        if summary.puede_saltar_mapeo:
            logger.info(
                f'[DIAG] ¡Mapeo automático! Saltando pantalla de mapeo '
                f'({summary.auto} automáticas, {summary.review} revisión, '
                f'{summary.manual} manuales, confianza={summary.confianza_promedio:.1f}%).'
            )
            logger.info(
                f'[DIAG] ¡Mapeo 100% automático! Saltando pantalla de mapeo '
                f'({summary.auto} columnas mapeadas automáticamente).'
            )
            # Guardar en sesión
            request.session['mapping_data'] = {str(k): v for k, v in mapeo_idx.items()}
            request.session['modo_importacion'] = 'crear'
            request.session['mapeo_saltado'] = True

            # Guardar automáticamente en la memoria de mapeo
            guardar_memoria_mapeo(formulario, encabezados, mapeo_idx)

            # Validación avanzada de estructura
            validacion = validar_estructura(
                formulario, encabezados, filas, mapeo_idx, match_results
            )

            if not validacion['valido']:
                for error in validacion['errores']:
                    messages.error(request, error)
                _t_total = time.perf_counter()
                logger.info(
                    f'[DIAG] <<< PASO_SUBIR fin (saltada + errores → mapeo) | '
                    f'total: {(_t_total - _t_subir) * 1000:.1f}ms'
                )
                return render(request, 'dynamic_forms/importar_excel.html', {
                    'formulario': formulario,
                    'paso': 'mapeo',
                    'encabezados': encabezados,
                    'encabezados_con_idx': encabezados_con_idx,
                    'campos_activos': campos_activos,
                    'mapeo_idx': mapeo_idx,
                    'sin_mapear': sin_mapear,
                    'total_filas': len(filas),
                    'analysis_meta': analysis,
                    'match_results': match_results,
                    'calidad': analysis.get('calidad', {}),
                    'conflictos_globales': analysis.get('conflictos_globales', []),
                    'tipo_campos': tipo_campos,
                    'auto_summary': _summary_to_dict(summary),
                    'es_admin': es_administrador(request.user),
                    'rol_usuario': rol_usuario(request.user),
                })

            # Preview de validación de filas
            preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
            validas = [r for r in preview if r['valida']]
            con_errores = [r for r in preview if not r['valida']]
            modo_msg = MODOS_IMPORTACION.get('crear', 'Crear')

            _t_total = time.perf_counter()
            logger.info(
                f'[DIAG] <<< PASO_SUBIR fin (saltando a preview) | '
                f'total: {(_t_total - _t_subir) * 1000:.1f}ms'
            )
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'preview',
                'preview': preview,
                'validas': validas,
                'con_errores': con_errores,
                'total_filas': len(filas),
                'validacion': validacion,
                'modo_actual': 'crear',
                'modo_msg': modo_msg,
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
                'analysis_meta': request.session.get('analysis_meta'),
                'calidad': analysis.get('calidad', {}),
                'conflictos_globales': analysis.get('conflictos_globales', []),
                'tipo_campos': tipo_campos,
                'auto_summary': _summary_to_dict(summary),
                'mapeo_saltado': True,
            })

        # Log motivos por los que NO se saltó el mapeo
        motivos = getattr(summary, 'motivo_no_saltar', [])
        if motivos:
            logger.info(f'[DIAG] Motivos para mostrar pantalla de mapeo ({len(motivos)}):')
            for m in motivos:
                logger.info(f'[DIAG]   → {m}')
            if len(motivos) <= 5:
                for m in motivos:
                    messages.info(request, m)
        else:
            logger.info(f'[DIAG] Mostrando pantalla de mapeo (sin motivos específicos) '
                        f'Auto={summary.auto} Review={summary.review} Manual={summary.manual}')

        _diag_log('post_analysis (mapeo + session)', _t_post)

        _t_render = _diag_start('render (mapeo template)')
        response = render(request, 'dynamic_forms/importar_excel.html', {
            'formulario': formulario,
            'paso': 'mapeo',
            'encabezados': encabezados,
            'encabezados_con_idx': encabezados_con_idx,
            'campos_activos': campos_activos,
            'mapeo_idx': mapeo_idx,
            'sin_mapear': sin_mapear,
            'total_filas': len(filas),
            'analysis_meta': analysis,
            'match_results': match_results,
            'calidad': analysis.get('calidad', {}),
            'conflictos_globales': analysis.get('conflictos_globales', []),
            'tipo_campos': tipo_campos,
            'auto_summary': _summary_to_dict(summary),
            'es_admin': es_administrador(request.user),
            'rol_usuario': rol_usuario(request.user),
        })
        _diag_log('render (mapeo template)', _t_render)

        _t_total = time.perf_counter()
        logger.info(
            f'[DIAG] <<< PASO_SUBIR fin | total: {(_t_total - _t_subir) * 1000:.1f}ms | '
            f'total_acumulado: {(_t_total - _t0) * 1000:.1f}ms'
        )
        return response

    return render(request, 'dynamic_forms/importar_excel.html', {
        'formulario': formulario,
        'paso': 'subir',
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def descargar_plantilla(request, formulario_id):
    """
    Descarga una plantilla Excel con la definición del formulario.
    """
    formulario = get_object_or_404(Formulario, id=formulario_id)

    try:
        buffer = generar_plantilla_excel(formulario)
    except Exception as e:
        logger.exception(f'Error generando plantilla para {formulario.nombre}: {e}')
        messages.error(request, f'Error al generar la plantilla: {e}')
        return redirect('dynamic_forms:ver_registros', formulario_id=formulario.id)

    nombre_archivo = f'plantilla_{formulario.nombre.lower().replace(" ", "_")}.xlsx'
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


@login_required(login_url='login')
@admin_required
def descargar_errores_importacion(request, formulario_id):
    """
    Descarga un Excel con los errores de la última importación.
    """
    errores = request.session.pop('ultimos_errores', None)
    nombre_form = request.session.pop('formulario_nombre_errores', 'importacion')

    if not errores:
        messages.info(request, 'No hay errores para descargar.')
        return redirect('dynamic_forms:importar_excel', formulario_id=formulario_id)

    buffer = generar_excel_errores(nombre_form, errores)
    if buffer is None:
        messages.info(request, 'No hay errores para descargar.')
        return redirect('dynamic_forms:importar_excel', formulario_id=formulario_id)

    nombre_archivo = f'errores_importacion_{nombre_form.lower().replace(" ", "_")}.xlsx'
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


@login_required(login_url='login')
@admin_required
def exportar_excel(request, formulario_id):
    """Genera archivo Excel con todos los registros y sus valores."""
    formulario = get_object_or_404(Formulario, id=formulario_id)
    campos = formulario.campos.filter(activo=True)
    registros = Registro.objects.filter(
        formulario=formulario
    ).select_related('usuario').order_by('-fecha_creacion')

    return exportar_registros_excel(registros, campos, formulario.nombre, relacion_resolver=_resolver_valores_relacion)


# ======================================================================
# Enterprise Import/Export — History, detail, rollback
# ======================================================================


@login_required(login_url='login')
@admin_required
def historial_importaciones(request, formulario_id):
    formulario = get_object_or_404(Formulario, id=formulario_id)
    importaciones = ImportLog.objects.filter(formulario=formulario).select_related('usuario').order_by('-fecha')
    page_obj = Paginator(importaciones, 25).get_page(request.GET.get('page'))

    for imp in page_obj:
        imp.quality_display = f'{"★" * imp.calidad_estrellas}{"☆" * (5 - imp.calidad_estrellas)}'

    return render(request, 'dynamic_forms/import_export/historial_importaciones.html', {
        'formulario': formulario,
        'page_obj': page_obj,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
        'hay_importaciones': importaciones.exists(),
    })


@login_required(login_url='login')
@admin_required
def detalle_importacion(request, import_log_id):
    import_log = get_object_or_404(
        ImportLog.objects.select_related('formulario', 'usuario'),
        id=import_log_id,
    )
    audits = ImportAudit.objects.filter(import_log=import_log).order_by('created_at')
    snapshots = ImportSnapshot.objects.filter(import_log=import_log).select_related('registro')

    try:
        resultado = json.loads(import_log.resultado_json) if import_log.resultado_json else {}
    except (json.JSONDecodeError, TypeError):
        resultado = {}

    page_obj = Paginator(audits, 50).get_page(request.GET.get('page'))

    return render(request, 'dynamic_forms/import_export/detalle_importacion.html', {
        'import_log': import_log,
        'page_obj': page_obj,
        'total_audits': audits.count(),
        'total_snapshots': snapshots.count(),
        'resultado': resultado,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def revertir_importacion(request, import_log_id):
    import_log = get_object_or_404(
        ImportLog.objects.select_related('formulario', 'usuario'),
        id=import_log_id,
    )

    if request.method == 'POST':
        from apps.platform.dynamic_forms.import_export.rollback import RollbackManager
        rm = RollbackManager()
        try:
            result = rm.revert(import_log_id)
            if result.get('errors'):
                for err in result['errors'][:5]:
                    messages.warning(request, err)
            messages.success(request, f'Importación revertida: {result["reverted_count"]} registros afectados.')
        except Exception as e:
            messages.error(request, f'Error al revertir: {e}')
        return redirect('dynamic_forms:detalle_importacion', import_log_id=import_log_id)

    return render(request, 'dynamic_forms/import_export/revertir_importacion.html', {
        'import_log': import_log,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def descargar_reporte_errores(request, import_log_id):
    import_log = get_object_or_404(
        ImportLog.objects.select_related('formulario', 'usuario'),
        id=import_log_id,
    )
    audits = ImportAudit.objects.filter(import_log=import_log, tipo='error').order_by('created_at')

    if not audits.exists():
        messages.info(request, 'No hay errores registrados en esta importación.')
        return redirect('dynamic_forms:detalle_importacion', import_log_id=import_log_id)

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Errores'
    ws.append(['ID', 'Tipo', 'Campo', 'Valor Anterior', 'Valor Nuevo', 'Mensaje', 'Fecha'])

    for a in audits:
        ws.append([
            a.id, a.tipo, a.campo_nombre, a.valor_anterior[:100], a.valor_nuevo[:100],
            a.mensaje, a.created_at.isoformat(),
        ])

    from io import BytesIO
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="errores_importacion_{import_log.id}.xlsx"'
    return response
