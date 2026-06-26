"""
Management command para asignar el hook post_crear_venta al formulario Ventas.

Uso:
    python manage.py asignar_hook_ventas
"""

from django.core.management.base import BaseCommand

from ...models import Formulario


class Command(BaseCommand):
    help = 'Asigna el hook post_crear_venta al formulario Ventas.'

    def handle(self, *args, **options):
        try:
            formulario = Formulario.objects.get(nombre='Ventas')
        except Formulario.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                'No existe el formulario "Ventas". Ejecuta sembrar_formularios_base primero.'
            ))
            return

        hook_path = 'apps.legacy.ventas.hooks.post_crear_venta'
        formulario.hook_post_crear = hook_path
        formulario.save(update_fields=['hook_post_crear'])

        self.stdout.write(self.style.SUCCESS(
            f'Hook post_crear asignado a "Ventas": {hook_path}'
        ))
