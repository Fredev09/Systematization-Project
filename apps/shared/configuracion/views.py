from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from config.permissions import admin_required, rol_usuario
from .forms import ConfiguracionTiendaForm
from .models import ConfiguracionTienda


@login_required(login_url='login')
@admin_required
def configuracion_sistema(request):
    configuracion = ConfiguracionTienda.obtener()

    if request.method == 'POST':
        form = ConfiguracionTiendaForm(request.POST, instance=configuracion)

        if form.is_valid():
            form.save()
            messages.success(request, 'Configuración actualizada correctamente.')
            return redirect('configuracion_sistema')

        messages.error(request, 'No se pudo guardar la configuración. Revisa los datos ingresados.')
    else:
        form = ConfiguracionTiendaForm(instance=configuracion)

    return render(request, 'configuracion/configuracion.html', {
        'form': form,
        'configuracion': configuracion,
        'rol_usuario': rol_usuario(request.user),
    })
