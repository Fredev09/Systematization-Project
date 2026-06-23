from django.contrib import admin

from .models import Campo, Formulario, Registro, ValorCampo


class CampoInline(admin.TabularInline):
    model = Campo
    extra = 1


class ValorCampoInline(admin.TabularInline):
    model = ValorCampo
    extra = 0
    readonly_fields = ('campo', 'valor')


@admin.register(Formulario)
class FormularioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo', 'fecha_creacion', 'total_campos', 'total_registros')
    list_filter = ('activo',)
    search_fields = ('nombre', 'descripcion')
    inlines = [CampoInline]

    def total_campos(self, obj):
        return obj.campos.count()
    total_campos.short_description = 'Campos'

    def total_registros(self, obj):
        return obj.registros.count()
    total_registros.short_description = 'Registros'


@admin.register(Campo)
class CampoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'formulario', 'tipo', 'obligatorio', 'orden')
    list_filter = ('tipo', 'obligatorio', 'formulario')
    search_fields = ('nombre',)


@admin.register(Registro)
class RegistroAdmin(admin.ModelAdmin):
    list_display = ('id', 'formulario', 'fecha_creacion', 'usuario')
    list_filter = ('formulario', 'fecha_creacion')
    inlines = [ValorCampoInline]
