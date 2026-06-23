from django.urls import path
from . import views

urlpatterns = [
    path('', views.listar_productos, name='productos'),
    path('agregar/', views.agregar_producto, name='agregar_producto'),
    path('agregar-categoria/', views.agregar_categoria, name='agregar_categoria'),
    path('crear-categoria/', views.crear_categoria, name='crear_categoria'),
    path('editar/<int:producto_id>/', views.editar_producto, name='editar_producto'),
    path('stock/<int:producto_id>/', views.actualizar_stock, name='actualizar_stock'),
    path('eliminar/<int:producto_id>/', views.eliminar_producto, name='eliminar_producto'),
    path('inventario/', views.inventario, name='inventario'),
    path('historial-inventario/', views.historial_inventario, name='historial_inventario'),
    path('historial-inventario/exportar-excel/', views.exportar_historial_inventario_excel, name='exportar_historial_inventario_excel'),
]