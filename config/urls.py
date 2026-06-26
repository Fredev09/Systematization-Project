from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.legacy.productos.views_dynamic import (
    actualizar_stock,
    agregar_categoria,
    agregar_producto,
    catalogo_publico,
    crear_categoria,
    editar_producto,
    eliminar_producto,
    exportar_historial_inventario_excel,
    historial_inventario,
    inventario,
    listar_productos,
)
from apps.legacy.productos import views as productos_views
from apps.legacy.ventas.views_dynamic import (
    cambiar_estado_cliente,
    clientes,
    detalle_cliente,
    editar_cliente,
    exportar_ventas,
    historial_ventas,
    nueva_venta,
)
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.inicio, name='inicio'),
    path('formulario/', views.formulario, name='formulario'),
    path('dashboard/', views.dashboard, name='dashboard'),
    # Productos — Dynamic Forms (CRUD + Inventario)
    path('productos/', listar_productos, name='productos'),
    path('productos/agregar/', agregar_producto, name='agregar_producto'),
    path('productos/editar/<int:producto_id>/', editar_producto, name='editar_producto'),
    path('productos/eliminar/<int:producto_id>/', eliminar_producto, name='eliminar_producto'),
    # Productos — categorías (Dynamic Forms — opciones dinámicas)
    path('productos/agregar-categoria/', agregar_categoria, name='agregar_categoria'),
    path('productos/crear-categoria/', crear_categoria, name='crear_categoria'),
    # Productos — Inventario (Dynamic Forms)
    path('productos/stock/<int:producto_id>/', actualizar_stock, name='actualizar_stock'),
    path('productos/inventario/', inventario, name='inventario'),
    path('productos/historial-inventario/', historial_inventario, name='historial_inventario'),
    path('productos/historial-inventario/exportar-excel/', exportar_historial_inventario_excel, name='exportar_historial_inventario_excel'),
    # Ventas — Dynamic Forms (migrados)
    path('venta/nueva/', nueva_venta, name='nueva_venta'),
    path('venta/historial/', historial_ventas, name='historial_ventas'),
    path('venta/clientes/<int:cliente_id>/', detalle_cliente, name='detalle_cliente'),
    # Ventas — vistas legacy (pendientes de migrar)
    path('venta/exportar/', exportar_ventas, name='exportar_ventas'),
    path('venta/clientes/', clientes, name='clientes'),
    path('venta/clientes/<int:cliente_id>/editar/', editar_cliente, name='editar_cliente'),
    path('venta/clientes/<int:cliente_id>/estado/', cambiar_estado_cliente, name='cambiar_estado_cliente'),
    # Otros módulos
    path('configuracion/', include('apps.shared.configuracion.urls')),
    path('', include('apps.shared.usuarios.urls')),
    path('catalogo/', catalogo_publico, name='catalogo_publico'),
    path('reportes/', include('apps.shared.reportes.urls')),
    path('forms/', include('apps.platform.dynamic_forms.urls')),
    path('', views.index, name='index'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
