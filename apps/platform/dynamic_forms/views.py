import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from config.pagination import OPCIONES_POR_PAGINA, obtener_por_pagina, parametros_sin_pagina
from config.permissions import admin_required, es_administrador, rol_usuario
from .forms import FormularioForm
from .import_service import (
    construir_mapeo_completo,
    detectar_columnas,
    importar,
    leer_excel,
    previsualizar,
)
from .models import Campo, Formulario, Registro, ValorCampo
from .services import _evaluar_formula, exportar_registros_excel
from .services_dynamic import _guardar_archivo_subido
from .validators import _validar_valor_campo


def _procesar_campos_post(request, formulario):
    """Procesa los campos enviados vía POST y devuelve errores y datos."""
    nombres = request.POST.getlist('campo_nombre')
    tipos = request.POST.getlist('campo_tipo')
    obligatorios = request.POST.getlist('campo_obligatorio')
    ordenes = request.POST.getlist('campo_orden')
    opciones_list = request.POST.getlist('campo_opciones')
    form_destino_ids = request.POST.getlist('campo_formulario_destino')
    formulas = request.POST.getlist('campo_formula')

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
        orden = ordenes[i] if i < len(ordenes) else '0'
        opciones_raw = opciones_list[i] if i < len(opciones_list) else ''

        opciones = None
        if tipo == 'lista' and opciones_raw:
            opciones = [
                op.strip()
                for op in opciones_raw.split(',')
                if op.strip()
            ]

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

        campos_procesados.append({
            'nombre': nombre,
            'tipo': tipo,
            'obligatorio': es_obligatorio,
            'orden': int(orden) if orden.isdigit() else 0,
            'opciones': opciones,
            'formulario_destino_id': formulario_destino_id,
            'formula': formula,
        })

    return campos_procesados, errores


def _sincronizar_campos(formulario, campos_procesados):
    """
    Sincroniza los campos de un formulario sin eliminar datos existentes:
    - Crea campos nuevos.
    - Actualiza campos existentes (por nombre).
    - Marca como inactivos (activo=False) los campos que ya no están en la lista.
    - Reactiva campos que vuelven a aparecer.
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

            if 'formulario_destino_id' in datos:
                campo.formulario_destino_id = datos['formulario_destino_id']
                update_fields.append('formulario_destino_id')
            if 'formula' in datos:
                campo.formula = datos.get('formula')
                update_fields.append('formula')

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
            if 'formulario_destino_id' in datos:
                kwargs['formulario_destino_id'] = datos['formulario_destino_id']
            if 'formula' in datos:
                kwargs['formula'] = datos.get('formula')

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

    return render(request, 'dynamic_forms/ver_registros.html', {
        'formulario': formulario,
        'campos': campos,
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
    Paso 2: POST (subir) → parsear Excel, detectar mapeo, mostrar preview
    Paso 3: POST (confirmar) → validar filas, mostrar resumen de validación
    Paso 4: POST (importar) → ejecutar importación
    """
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )
    campos_activos = formulario.campos.filter(activo=True).order_by('orden')

    paso = request.POST.get('paso', 'subir')

    # --- Paso 4: Ejecutar importación ---
    if paso == 'importar':
        import_data = request.session.pop('import_data', None)
        mapping_data = request.session.pop('mapping_data', None)
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

        resultado = importar(formulario, filas_validas, usuario=request.user)

        return render(request, 'dynamic_forms/importar_excel.html', {
            'formulario': formulario,
            'paso': 'resultado',
            'resultado': resultado,
            'es_admin': es_administrador(request.user),
            'rol_usuario': rol_usuario(request.user),
        })

    # --- Paso 3: Previsualizar validación (confirmar mapeo) ---
    if paso == 'confirmar':
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

        mapeo_idx, sin_mapear = construir_mapeo_completo(encabezados, formulario, mapeo_usuario)

        # Validar que campos obligatorios estén mapeados
        errores_mapeo = []
        for campo in campos_activos:
            if campo.obligatorio and campo.tipo not in ('calculado', 'imagen', 'archivo'):
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
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })

        # Previsualizar validación
        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        validas = [r for r in preview if r['valida']]
        con_errores = [r for r in preview if not r['valida']]

        request.session['import_data'] = import_data
        request.session['mapping_data'] = {str(k): v for k, v in mapeo_idx.items()}

        return render(request, 'dynamic_forms/importar_excel.html', {
            'formulario': formulario,
            'paso': 'preview',
            'preview': preview,
            'validas': validas,
            'con_errores': con_errores,
            'total_filas': len(filas),
            'es_admin': es_administrador(request.user),
            'rol_usuario': rol_usuario(request.user),
        })

    # --- Paso 1: Mostrar formulario de subida ---
    if request.method == 'POST' and paso == 'subir':
        archivo = request.FILES.get('archivo_excel')
        if not archivo:
            messages.error(request, 'Debes seleccionar un archivo Excel.')
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'subir',
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })

        if not archivo.name.endswith('.xlsx'):
            messages.error(request, 'Solo se aceptan archivos .xlsx.')
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'subir',
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })

        # Leer archivo
        try:
            encabezados, filas = leer_excel(archivo)
        except ValueError as e:
            messages.error(request, str(e))
            return render(request, 'dynamic_forms/importar_excel.html', {
                'formulario': formulario,
                'paso': 'subir',
                'es_admin': es_administrador(request.user),
                'rol_usuario': rol_usuario(request.user),
            })

        # Detectar mapeo automático
        mapeo_idx, sin_mapear = construir_mapeo_completo(encabezados, formulario)

        # Guardar datos en sesión
        request.session['import_data'] = {
            'encabezados': encabezados,
            'filas': filas,
        }

        encabezados_con_idx = [(idx, nombre) for idx, nombre in enumerate(encabezados)]

        return render(request, 'dynamic_forms/importar_excel.html', {
            'formulario': formulario,
            'paso': 'mapeo',
            'encabezados': encabezados,
            'encabezados_con_idx': encabezados_con_idx,
            'campos_activos': campos_activos,
            'mapeo_idx': mapeo_idx,
            'sin_mapear': sin_mapear,
            'total_filas': len(filas),
            'es_admin': es_administrador(request.user),
            'rol_usuario': rol_usuario(request.user),
        })

    return render(request, 'dynamic_forms/importar_excel.html', {
        'formulario': formulario,
        'paso': 'subir',
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


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
