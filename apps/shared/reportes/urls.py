from django.urls import path
from . import views

urlpatterns = [
    path('', views.reportes, name='reportes'),
    path('excel/', views.exportar_reporte_excel, name='reporte_excel'),
    path('pdf/completo/', views.exportar_reporte_completo_pdf, name='reporte_pdf_completo'),
    path('pdf/ventas/', views.exportar_reporte_ventas_pdf, name='reporte_pdf_ventas'),
    path('pdf/inventario/', views.exportar_reporte_inventario_pdf, name='reporte_pdf_inventario'),
]