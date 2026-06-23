from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from config.pagination import OPCIONES_POR_PAGINA, obtener_por_pagina, parametros_sin_pagina
from config.permissions import admin_required, es_administrador, rol_usuario
from .forms import CampoForm, FormularioForm
from .models import Campo, Formulario, Registro, ValorCampo
from .services import exportar_registros_excel


@login_required(login_url='login')
@admin_required
def listar_formularios(request):
    """Vista para administradores que muestra todos los formularios en tarjetas."""
    formularios = Formulario.objects.all().order_by('-fecha_creacion')

    for f in formularios:
        f.total_campos = f.campos.count()
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

                nombres = request.POST.getlist('campo_nombre')
                tipos = request.POST.getlist('campo_tipo')
                obligatorios = request.POST.getlist('campo_obligatorio')
                ordenes = request.POST.getlist('campo_orden')
                opciones_list = request.POST.getlist('campo_opciones')

                errores = []
                for i, nombre in enumerate(nombres):
                    nombre = nombre.strip()
                    if not nombre:
                        continue

                    if Campo.objects.filter(formulario=formulario, nombre=nombre).exists():
                        errores.append(f'El campo "{nombre}" ya existe en este formulario.')
                        continue

                    tipo = tipos[i] if i < len(tipos) else 'texto'
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

                    Campo.objects.create(
                        formulario=formulario,
                        nombre=nombre,
                        tipo=tipo,
                        obligatorio=es_obligatorio,
                        orden=int(orden) if orden.isdigit() else 0,
                        opciones=opciones,
                    )

                if not nombres or not any(n.strip() for n in nombres):
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

                if errores:
                    for error in errores:
                        messages.warning(request, error)

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
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


@login_required(login_url='login')
@admin_required
def editar_formulario(request, formulario_id):
    """Editar formulario y sus campos."""
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )

    if request.method == 'POST':
        form = FormularioForm(request.POST, instance=formulario)

        if form.is_valid():
            with transaction.atomic():
                formulario = form.save()

                # Eliminar campos existentes
                formulario.campos.all().delete()

                nombres = request.POST.getlist('campo_nombre')
                tipos = request.POST.getlist('campo_tipo')
                obligatorios = request.POST.getlist('campo_obligatorio')
                ordenes = request.POST.getlist('campo_orden')
                opciones_list = request.POST.getlist('campo_opciones')

                for i, nombre in enumerate(nombres):
                    nombre = nombre.strip()
                    if not nombre:
                        continue

                    tipo = tipos[i] if i < len(tipos) else 'texto'
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

                    Campo.objects.create(
                        formulario=formulario,
                        nombre=nombre,
                        tipo=tipo,
                        obligatorio=es_obligatorio,
                        orden=int(orden) if orden.isdigit() else 0,
                        opciones=opciones,
                    )

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
        'campos': formulario.campos.all(),
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
    """Vista para administrar campos de un formulario específico."""
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )

    if request.method == 'POST':
        with transaction.atomic():
            formulario.campos.all().delete()

            nombres = request.POST.getlist('campo_nombre')
            tipos = request.POST.getlist('campo_tipo')
            obligatorios = request.POST.getlist('campo_obligatorio')
            ordenes = request.POST.getlist('campo_orden')
            opciones_list = request.POST.getlist('campo_opciones')

            for i, nombre in enumerate(nombres):
                nombre = nombre.strip()
                if not nombre:
                    continue

                tipo = tipos[i] if i < len(tipos) else 'texto'
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

                Campo.objects.create(
                    formulario=formulario,
                    nombre=nombre,
                    tipo=tipo,
                    obligatorio=es_obligatorio,
                    orden=int(orden) if orden.isdigit() else 0,
                    opciones=opciones,
                )

        messages.success(
            request,
            f'Campos de "{formulario.nombre}" actualizados correctamente.'
        )
        return redirect('dynamic_forms:listar_formularios')

    return render(request, 'dynamic_forms/gestionar_campos.html', {
        'formulario': formulario,
        'campos': formulario.campos.all(),
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })


def llenar_formulario(request, formulario_id):
    """Vista PÚBLICA que renderiza el formulario dinámico y guarda registros."""
    formulario = get_object_or_404(
        Formulario.objects.prefetch_related('campos'),
        id=formulario_id
    )

    if not formulario.activo:
        return render(request, 'dynamic_forms/llenar_formulario.html', {
            'formulario': formulario,
            'formulario_inactivo': True,
            'es_admin': es_administrador(request.user) if request.user.is_authenticated else False,
            'rol_usuario': rol_usuario(request.user) if request.user.is_authenticated else '',
        })

    campos = formulario.campos.all()

    if request.method == 'POST':
        with transaction.atomic():
            registro = Registro.objects.create(
                formulario=formulario,
                usuario=request.user if request.user.is_authenticated else None
            )

            errores = []
            for campo in campos:
                valor_raw = request.POST.get(f'campo_{campo.id}', '').strip()

                if campo.obligatorio and not valor_raw:
                    errores.append(f'El campo "{campo.nombre}" es obligatorio.')
                    continue

                if valor_raw:
                    if campo.tipo == 'numero':
                        try:
                            float(valor_raw.replace(',', '.'))
                        except ValueError:
                            errores.append(
                                f'El campo "{campo.nombre}" debe ser un número válido.'
                            )
                            continue
                    elif campo.tipo == 'fecha':
                        from datetime import datetime
                        try:
                            datetime.strptime(valor_raw, '%Y-%m-%d')
                        except ValueError:
                            errores.append(
                                f'El campo "{campo.nombre}" debe ser una fecha válida (YYYY-MM-DD).'
                            )
                            continue
                    elif campo.tipo == 'lista' and campo.opciones:
                        if valor_raw not in campo.opciones:
                            errores.append(
                                f'El valor "{valor_raw}" no es una opción válida para "{campo.nombre}".'
                            )
                            continue
                    elif campo.tipo == 'booleano':
                        valor_raw = 'Sí' if valor_raw == 'on' else 'No'

                    ValorCampo.objects.create(
                        registro=registro,
                        campo=campo,
                        valor=valor_raw,
                    )

            if errores:
                transaction.set_rollback(True)
                return render(request, 'dynamic_forms/llenar_formulario.html', {
                    'formulario': formulario,
                    'campos': campos,
                    'errores': errores,
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
    campos = formulario.campos.all()

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
def exportar_excel(request, formulario_id):
    """Genera archivo Excel con todos los registros y sus valores."""
    formulario = get_object_or_404(Formulario, id=formulario_id)
    campos = formulario.campos.all()
    registros = Registro.objects.filter(
        formulario=formulario
    ).select_related('usuario').order_by('-fecha_creacion')

    return exportar_registros_excel(registros, campos, formulario.nombre)
