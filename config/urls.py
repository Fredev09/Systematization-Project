from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.legacy.productos.views import catalogo_publico
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.inicio, name='inicio'),
    path('formulario/', views.formulario, name='formulario'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('productos/', include('apps.legacy.productos.urls')),
    path('configuracion/', include('apps.shared.configuracion.urls')),
    path('', include('apps.shared.usuarios.urls')),
    path('venta/', include('apps.legacy.ventas.urls')),
    path('catalogo/', catalogo_publico, name='catalogo_publico'),
    path('reportes/', include('apps.shared.reportes.urls')),
    path('forms/', include('apps.platform.dynamic_forms.urls')),
    path('', views.index, name='index'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
