from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.iniciarSesion, name='login'),
    path('logout/', views.cerrarSesion, name='logout'),
    path('recuperar-contrasena/', views.recuperarContraseña, name='recuperar_contrasena'),
    path('usuarios/', views.gestionUsuarios, name='usuarios'),
    path('usuarios/crear/', views.crearVendedor, name='crear_vendedor'),
    path('usuarios/exportar/', views.exportarVendedoresExcel, name='exportar_vendedores_excel'),
    path('usuarios/<int:usuario_id>/editar/', views.editarVendedor, name='editar_vendedor'),
    path('usuarios/<int:usuario_id>/cambiar-estado/', views.cambiarEstadoUsuario, name='cambiar_estado_usuario'),
]
