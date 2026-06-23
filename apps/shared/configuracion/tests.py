from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import ConfiguracionTienda


class ConfiguracionTiendaTests(TestCase):
    def test_obtener_crea_configuracion_por_defecto(self):
        configuracion = ConfiguracionTienda.obtener()

        self.assertEqual(configuracion.pk, 1)
        self.assertEqual(configuracion.nombre_tienda, 'Tonjeo')
        self.assertEqual(configuracion.stock_minimo_alerta, 5)
        self.assertEqual(configuracion.tema_defecto, 'dark')

    def test_solo_existe_una_configuracion(self):
        configuracion = ConfiguracionTienda.obtener()
        configuracion.nombre_tienda = 'Nueva tienda'
        configuracion.save()

        ConfiguracionTienda.objects.create(nombre_tienda='Otra tienda')

        self.assertEqual(ConfiguracionTienda.objects.count(), 1)
        self.assertEqual(ConfiguracionTienda.obtener().nombre_tienda, 'Otra tienda')

    def test_admin_puede_actualizar_configuracion(self):
        admin = User.objects.create_superuser(
            username='admin',
            email='admin@correo.com',
            password='admin12345'
        )
        self.client.login(username='admin', password='admin12345')

        response = self.client.post(reverse('configuracion_sistema'), {
            'nombre_tienda': 'Tonjeo Demo',
            'telefono': '3001234567',
            'direccion': 'Centro comercial',
            'correo': 'demo@correo.com',
            'stock_minimo_alerta': 8,
            'tema_defecto': 'light',
            'mostrar_agotados_catalogo': 'on',
        })

        self.assertEqual(response.status_code, 302)

        configuracion = ConfiguracionTienda.obtener()
        self.assertEqual(configuracion.nombre_tienda, 'Tonjeo Demo')
        self.assertEqual(configuracion.stock_minimo_alerta, 8)
        self.assertEqual(configuracion.tema_defecto, 'light')
