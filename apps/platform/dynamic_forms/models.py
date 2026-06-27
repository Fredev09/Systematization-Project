from django.db import models


# ---------------------------------------------------------------------------
# Funciones auxiliares para importar hooks/validaciones desde paths Python
# ---------------------------------------------------------------------------
import importlib
import logging

logger = logging.getLogger(__name__)


def _importar_funcion(path):
    """Importa una función desde un path Python 'modulo.submodulo.funcion'.
    Retorna la función o None si no se puede importar."""
    if not path:
        return None
    try:
        parts = path.rsplit('.', 1)
        if len(parts) != 2:
            logger.warning(f'Formato de path inválido: {path}. Debe ser "modulo.funcion".')
            return None
        module_path, func_name = parts
        module = importlib.import_module(module_path)
        return getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        logger.warning(f'No se pudo importar "{path}": {e}')
        return None


class Formulario(models.Model):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)
    creado_por = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)

    # ------------------------------------------------------------------ #
    # Hooks: paths Python a funciones que se ejecutan después de crear o  #
    # actualizar un registro en este formulario.                          #
    # Formato: "modulo.submodulo.nombre_funcion"                          #
    # Ej: "apps.legacy.ventas.hooks.post_crear_venta"                     #
    # ------------------------------------------------------------------ #
    hook_post_crear = models.TextField(
        blank=True, null=True,
        help_text='Path Python a la función post-creación. Ej: apps.misw.hooks.post_crear'
    )
    hook_post_actualizar = models.TextField(
        blank=True, null=True,
        help_text='Path Python a la función post-actualización. Ej: apps.misw.hooks.post_actualizar'
    )
    validacion_personalizada = models.TextField(
        blank=True, null=True,
        help_text='Path Python a la función de validación personalizada. Recibe (formulario, valores_dict) y retorna lista de errores.'
    )

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
        ('email', 'Correo electrónico'),
        ('url', 'URL'),
        ('telefono', 'Teléfono'),
        ('textarea', 'Texto largo'),
        ('imagen', 'Imagen'),
        ('archivo', 'Archivo'),
        ('relacion', 'Relación'),
        ('calculado', 'Calculado'),
    )

    # Tipos que requieren subida de archivos
    TIPOS_ARCHIVO = {'imagen', 'archivo'}
    # Tipos que son de solo lectura
    TIPOS_SOLO_LECTURA = {'calculado'}
    # Tipos que requieren configuración extra
    TIPOS_RELACION = {'relacion'}

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
    activo = models.BooleanField(default=True)  # Para archivar campos sin perder datos
    unico = models.BooleanField(
        default=False,
        help_text='Si se activa, no pueden existir dos registros con el mismo valor en este campo.'
    )

    # Para tipo 'relacion': a qué formulario apunta
    formulario_destino = models.ForeignKey(
        Formulario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campos_origen'
    )
    # Para tipo 'calculado': fórmula a evaluar (ej: cantidad * precio)
    formula = models.TextField(blank=True, null=True)

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
    fecha_actualizacion = models.DateTimeField(auto_now=True)
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
        indexes = [
            models.Index(fields=['campo', 'valor'], name='idx_valorcampo_campo_valor'),
        ]

    def __str__(self):
        return f"{self.campo.nombre}: {self.valor[:50]}"
