from django.contrib import admin

from .models import ConfiguracionTienda


@admin.register(ConfiguracionTienda)
class ConfiguracionTiendaAdmin(admin.ModelAdmin):
    list_display = (
        'nombre_tienda',
        'telefono',
        'correo',
        'stock_minimo_alerta',
        'tema_defecto',
        'mostrar_agotados_catalogo',
        'fecha_actualizacion',
    )

    def has_add_permission(self, request):
        return not ConfiguracionTienda.objects.exists()
