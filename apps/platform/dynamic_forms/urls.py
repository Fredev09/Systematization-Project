from django.urls import path

from . import views

app_name = 'dynamic_forms'

urlpatterns = [
    path('', views.listar_formularios, name='listar_formularios'),
    path('crear/', views.crear_formulario, name='crear_formulario'),
    path('<int:formulario_id>/editar/', views.editar_formulario, name='editar_formulario'),
    path('<int:formulario_id>/eliminar/', views.eliminar_formulario, name='eliminar_formulario'),
    path('<int:formulario_id>/campos/', views.gestionar_campos, name='gestionar_campos'),
    path('<int:formulario_id>/llenar/', views.llenar_formulario, name='llenar_formulario'),
    path('<int:formulario_id>/registros/', views.ver_registros, name='ver_registros'),
    path('<int:formulario_id>/registros/<int:registro_id>/editar/', views.editar_registro, name='editar_registro'),
    path('<int:formulario_id>/exportar-excel/', views.exportar_excel, name='exportar_excel'),
    path('<int:formulario_id>/importar-excel/', views.importar_excel, name='importar_excel'),
    path('<int:formulario_id>/importar-excel/descargar-errores/', views.descargar_errores_importacion, name='descargar_errores_importacion'),
    path('<int:formulario_id>/descargar-plantilla/', views.descargar_plantilla, name='descargar_plantilla'),
    # Enterprise Import/Export
    path('<int:formulario_id>/historial-importaciones/', views.historial_importaciones, name='historial_importaciones'),
    path('<int:formulario_id>/importar-excel/historial/', views.historial_importaciones, name='historial_importaciones_alt'),
    path('importaciones/<int:import_log_id>/', views.detalle_importacion, name='detalle_importacion'),
    path('importaciones/<int:import_log_id>/revertir/', views.revertir_importacion, name='revertir_importacion'),
    path('importaciones/<int:import_log_id>/descargar-reporte-errores/', views.descargar_reporte_errores, name='descargar_reporte_errores'),
]
