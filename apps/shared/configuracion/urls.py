from django.urls import path

from . import views

urlpatterns = [
    path('', views.configuracion_sistema, name='configuracion_sistema'),
]
