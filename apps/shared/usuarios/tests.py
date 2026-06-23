from django.contrib.auth.models import Group, User
from django.test import TestCase

from backend.permissions import GRUPO_VENDEDOR, asegurar_grupos_base
from .forms import VendedorForm


class VendedorFormTests(TestCase):
    def test_formulario_vendedor_valido(self):
        form = VendedorForm(data={
            'first_name': 'Ana',
            'last_name': 'Gómez',
            'username': 'ana.gomez',
            'email': 'ana@example.com',
            'contra': 'clave123',
            'confirmarContra': 'clave123',
        })

        self.assertTrue(form.is_valid())

    def test_formulario_rechaza_contrasenas_diferentes(self):
        form = VendedorForm(data={
            'first_name': 'Ana',
            'last_name': 'Gómez',
            'username': 'ana.gomez',
            'email': 'ana@example.com',
            'contra': 'clave123',
            'confirmarContra': 'otra-clave',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('Las contraseñas no coinciden.', form.non_field_errors())

    def test_grupo_vendedor_base_se_crea_correctamente(self):
        asegurar_grupos_base()
        vendedor = User.objects.create_user(
            username='vendedor1',
            password='clave123'
        )
        grupo = Group.objects.get(name=GRUPO_VENDEDOR)
        vendedor.groups.add(grupo)

        self.assertTrue(vendedor.groups.filter(name=GRUPO_VENDEDOR).exists())
