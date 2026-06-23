from django.urls import path
from . import views

urlpatterns = [
    path('nueva/', views.nueva_venta, name='nueva_venta'),
    path('historial/', views.historial_ventas, name='historial_ventas'),
    path('exportar/', views.exportar_ventas, name='exportar_ventas'),
    path('clientes/', views.clientes, name='clientes'),
    path('clientes/<int:cliente_id>/', views.detalle_cliente, name='detalle_cliente'),
    path('clientes/<int:cliente_id>/editar/', views.editar_cliente, name='editar_cliente'),
    path('clientes/<int:cliente_id>/estado/', views.cambiar_estado_cliente, name='cambiar_estado_cliente'),
]