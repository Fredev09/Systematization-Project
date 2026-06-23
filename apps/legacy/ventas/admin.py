from django.contrib import admin

from .models import Cliente, Venta


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('id', 'documento', 'nombre', 'apellido', 'correo', 'telefono', 'activo')
    search_fields = ('documento', 'nombre', 'apellido', 'correo', 'telefono')
    list_filter = ('activo',)


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ('id', 'producto', 'vendedor', 'cliente', 'cantidad', 'total', 'fecha')
    search_fields = ('producto__nombre', 'vendedor__username', 'cliente__nombre', 'cliente__apellido')
    list_filter = ('fecha',)
