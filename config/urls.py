from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.legacy.productos.views import catalogo_publico
from apps.legacy.productos.views_dynamic import (
    actualizar_stock,
    agregar_producto,
    editar_producto,
    eliminar_producto,
    exportar_historial_inventario_excel,
    historial_inventario,
    inventario,
    listar_productos,
)
from apps.legacy.productos import views as productos_views
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
    # Productos — categorías legacy (pendientes de migrar a Dynamic Forms)
    path('productos/agregar-categoria/', productos_views.agregar_categoria, name='agregar_categoria'),
    path('productos/crear-categoria/', productos_views.crear_categoria, name='crear_categoria'),
    # Productos — Inventario (Dynamic Forms)
    path('productos/stock/<int:producto_id>/', actualizar_stock, name='actualizar_stock'),
    path('productos/inventario/', inventario, name='inventario'),
    path('productos/historial-inventario/', historial_inventario, name='historial_inventario'),
    path('productos/historial-inventario/exportar-excel/', exportar_historial_inventario_excel, name='exportar_historial_inventario_excel'),
    # Otros módulos
    path('configuracion/', include('apps.shared.configuracion.urls')),
    path('', include('apps.shared.usuarios.urls')),
    path('venta/', include('apps.legacy.ventas.urls')),
    path('catalogo/', catalogo_publico, name='catalogo_publico'),
    path('reportes/', include('apps.shared.reportes.urls')),
    path('forms/', include('apps.platform.dynamic_forms.urls')),
    path('', views.index, name='index'),
]

# ---------------------------------------------------------------------------
# Rutas paralelas para otros módulos dinámicos (Ventas, Dashboard)
# ---------------------------------------------------------------------------
from apps.legacy.ventas.views_dynamic import (
    nueva_venta as nueva_venta_dinamico,
    historial_ventas as historial_ventas_dinamico,
    detalle_cliente as detalle_cliente_dinamico,
)

urlpatterns += [
    path('venta-dinamico/nueva/', nueva_venta_dinamico, name='nueva_venta_dinamico'),
    path('venta-dinamico/historial/', historial_ventas_dinamico, name='historial_ventas_dinamico'),
    path('venta-dinamico/clientes/<int:cliente_id>/', detalle_cliente_dinamico, name='detalle_cliente_dinamico'),
    path('dashboard-dinamico/', views.dashboard_dinamico, name='dashboard_dinamico'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
