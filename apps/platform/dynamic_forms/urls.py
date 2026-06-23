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
    path('<int:formulario_id>/exportar-excel/', views.exportar_excel, name='exportar_excel'),
]
