from django.db import models


class Formulario(models.Model):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)
    creado_por = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)

    class Meta:
        verbose_name = 'Formulario'
        verbose_name_plural = 'Formularios'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return self.nombre


class Campo(models.Model):
    TIPOS = (
        ('texto', 'Texto'),
        ('numero', 'Número'),
        ('fecha', 'Fecha'),
        ('booleano', 'Booleano'),
        ('lista', 'Lista desplegable'),
    )

    formulario = models.ForeignKey(
        Formulario,
        on_delete=models.CASCADE,
        related_name='campos'
    )
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    obligatorio = models.BooleanField(default=False)
    orden = models.IntegerField(default=0)
    opciones = models.JSONField(blank=True, null=True)  # Para listas desplegables

    class Meta:
        ordering = ['orden']

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"


class Registro(models.Model):
    formulario = models.ForeignKey(
        Formulario,
        on_delete=models.CASCADE,
        related_name='registros'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = 'Registro'
        verbose_name_plural = 'Registros'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"Registro #{self.id} - {self.formulario.nombre}"


class ValorCampo(models.Model):
    registro = models.ForeignKey(
        Registro,
        on_delete=models.CASCADE,
        related_name='valores'
    )
    campo = models.ForeignKey(Campo, on_delete=models.CASCADE)
    valor = models.TextField()

    class Meta:
        unique_together = ['registro', 'campo']

    def __str__(self):
        return f"{self.campo.nombre}: {self.valor[:50]}"
