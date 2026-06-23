from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import Group
from django.shortcuts import redirect


GRUPO_ADMINISTRADOR = 'Administrador'
GRUPO_VENDEDOR = 'Vendedor'


def es_administrador(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=GRUPO_ADMINISTRADOR).exists()
    )


def es_vendedor(user):
    return user.is_authenticated and user.groups.filter(name=GRUPO_VENDEDOR).exists()


def rol_usuario(user):
    if es_administrador(user):
        return 'Administrador'
    if es_vendedor(user):
        return 'Vendedor'
    return 'Usuario'


def asegurar_grupos_base():
    Group.objects.get_or_create(name=GRUPO_ADMINISTRADOR)
    Group.objects.get_or_create(name=GRUPO_VENDEDOR)


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if es_administrador(request.user):
            return view_func(request, *args, **kwargs)

        messages.error(request, 'No tienes permisos para acceder a esta sección.')
        return redirect('dashboard')

    return _wrapped_view
