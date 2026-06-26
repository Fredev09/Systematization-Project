from django.contrib import admin

from .models import MovimientoInventario, Producto


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'nombre',
        'categoria',
        'talla',
        'color',
        'precio',
        'stock',
        'imagen_url',
    )
    search_fields = ('nombre', 'categoria__nombre', 'color', 'talla')
    list_filter = ('categoria', 'talla', 'color')


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'producto',
        'tipo',
        'motivo',
        'cantidad',
        'stock_anterior',
        'stock_nuevo',
        'fecha',
    )

    search_fields = ('producto__nombre', 'motivo', 'observacion')
    list_filter = ('tipo', 'motivo', 'fecha')
    readonly_fields = ('fecha',)