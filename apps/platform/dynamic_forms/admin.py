from django.contrib import admin

from .models import Campo, Formulario, ImportAudit, ImportLog, ImportSnapshot, Registro, ValorCampo


class CampoInline(admin.TabularInline):
    model = Campo
    fk_name = 'formulario'
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
    list_display = ('nombre', 'formulario', 'tipo', 'obligatorio', 'orden', 'identificador_principal', 'formula')
    list_filter = ('tipo', 'obligatorio', 'identificador_principal', 'formulario')
    search_fields = ('nombre',)


@admin.register(Registro)
class RegistroAdmin(admin.ModelAdmin):
    list_display = ('id', 'formulario', 'fecha_creacion', 'usuario')
    list_filter = ('formulario', 'fecha_creacion')
    inlines = [ValorCampoInline]


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'formulario', 'usuario', 'fecha', 'modo', 'estado', 'creados', 'actualizados', 'errores')
    list_filter = ('estado', 'modo', 'formulario')
    search_fields = ('archivo_nombre', 'resumen')
    readonly_fields = ('fecha', 'archivo_hash', 'tiempo_seg')
    date_hierarchy = 'fecha'


@admin.register(ImportAudit)
class ImportAuditAdmin(admin.ModelAdmin):
    list_display = ('id', 'import_log', 'tipo', 'registro_id', 'campo_nombre', 'created_at')
    list_filter = ('tipo',)
    search_fields = ('mensaje',)
    readonly_fields = ('created_at',)


@admin.register(ImportSnapshot)
class ImportSnapshotAdmin(admin.ModelAdmin):
    list_display = ('id', 'import_log', 'registro', 'created_at')
    readonly_fields = ('created_at',)
