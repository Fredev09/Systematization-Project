from django.db import models


class ConfiguracionTienda(models.Model):
    TEMA_CLARO = 'light'
    TEMA_OSCURO = 'dark'

    TEMA_CHOICES = [
        (TEMA_OSCURO, 'Oscuro'),
        (TEMA_CLARO, 'Claro'),
    ]

    nombre_tienda = models.CharField(max_length=100, default='Tonjeo')
    telefono = models.CharField(max_length=30, blank=True)
    direccion = models.CharField(max_length=150, blank=True)
    correo = models.EmailField(blank=True)
    stock_minimo_alerta = models.PositiveIntegerField(default=5)
    tema_defecto = models.CharField(
        max_length=10,
        choices=TEMA_CHOICES,
        default=TEMA_OSCURO
    )
    mostrar_agotados_catalogo = models.BooleanField(default=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de tienda'
        verbose_name_plural = 'Configuración de tienda'

    def __str__(self):
        return self.nombre_tienda

    def save(self, *args, **kwargs):
        self.pk = 1
        kwargs.pop('force_insert', None)
        super().save(*args, **kwargs)

    @classmethod
    def obtener(cls):
        configuracion, _ = cls.objects.get_or_create(pk=1)
        return configuracion
