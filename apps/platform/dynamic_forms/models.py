from __future__ import annotations

import importlib
import logging

from django.db import models

logger = logging.getLogger(__name__)


def _importar_funcion(path):
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
        ('moneda', 'Moneda'),
        ('porcentaje', 'Porcentaje'),
        ('fecha', 'Fecha'),
        ('hora', 'Hora'),
        ('fecha_hora', 'Fecha y hora'),
        ('booleano', 'Booleano'),
        ('lista', 'Lista desplegable'),
        ('email', 'Correo electrónico'),
        ('url', 'URL'),
        ('telefono', 'Teléfono'),
        ('documento', 'Documento de identidad'),
        ('codigo', 'Código'),
        ('codigo_barras', 'Código de barras'),
        ('qr', 'Código QR'),
        ('textarea', 'Texto largo'),
        ('imagen', 'Imagen'),
        ('archivo', 'Archivo'),
        ('relacion', 'Relación'),
        ('calculado', 'Calculado'),
        ('color', 'Color'),
        ('ip', 'Dirección IP'),
        ('uuid', 'UUID'),
        ('geolocalizacion', 'Geolocalización'),
        ('duracion', 'Duración'),
        ('estado', 'Estado'),
        ('categoria', 'Categoría'),
        ('tags', 'Etiquetas'),
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
    descripcion = models.TextField(
        blank=True, null=True,
        help_text='Descripción del campo para orientar al usuario.'
    )
    visible = models.BooleanField(
        default=True,
        help_text='Si está desactivado, el campo no se muestra en formularios ni tablas.'
    )
    activo = models.BooleanField(default=True)  # Para archivar campos sin perder datos
    unico = models.BooleanField(
        default=False,
        help_text='Si se activa, no pueden existir dos registros con el mismo valor en este campo.'
    )
    metadata_json = models.JSONField(
        blank=True, null=True,
        help_text='Configuración extendida: regex, min/max, decimales, default, placeholder, ayuda, etc.',
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

    # Identificador principal del formulario
    # Solo un campo por formulario puede tener esta marca
    identificador_principal = models.BooleanField(
        default=False,
        help_text='Marca este campo como el identificador principal del formulario. '
                  'Solo un campo por formulario puede tener esta marca.'
    )

    class Meta:
        ordering = ['orden']
        verbose_name = 'Campo'
        verbose_name_plural = 'Campos'

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"

    def save(self, *args, **kwargs):
        """Auto-desmarca otros campos del mismo formulario si este es el identificador principal."""
        if self.identificador_principal and self.pk is None:
            Campo.objects.filter(
                formulario=self.formulario,
                identificador_principal=True
            ).exclude(pk=self.pk).update(identificador_principal=False)
        super().save(*args, **kwargs)
        if self.identificador_principal:
            Campo.objects.filter(
                formulario=self.formulario,
                identificador_principal=True
            ).exclude(pk=self.pk).update(identificador_principal=False)


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


# ======================================================================
# ImportHistory — Trazabilidad completa de importaciones
# ======================================================================


class ImportLog(models.Model):
    ESTADOS = [
        ('completado', 'Completado'),
        ('revertido', 'Revertido'),
        ('parcial', 'Parcial'),
    ]
    MODOS = [
        ('crear', 'Solo crear'),
        ('actualizar', 'Solo actualizar'),
        ('upsert', 'UPSERT'),
        ('validar', 'Solo validar'),
    ]

    formulario = models.ForeignKey(Formulario, on_delete=models.CASCADE, related_name='importaciones')
    usuario = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    archivo_nombre = models.CharField(max_length=500)
    archivo_tamano = models.IntegerField(default=0)
    archivo_hash = models.CharField(max_length=64, blank=True, db_index=True)
    modo = models.CharField(max_length=20, choices=MODOS)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='completado')
    total_filas = models.IntegerField(default=0)
    creados = models.IntegerField(default=0)
    actualizados = models.IntegerField(default=0)
    ignorados = models.IntegerField(default=0)
    errores = models.IntegerField(default=0)
    tiempo_seg = models.FloatField(default=0.0)
    resumen = models.TextField(blank=True)
    hoja_detectada = models.CharField(max_length=200, blank=True)
    confianza_global = models.FloatField(default=0.0)
    calidad_estrellas = models.IntegerField(default=0)
    resultado_json = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Importación'
        verbose_name_plural = 'Importaciones'
        ordering = ['-fecha']

    def __str__(self):
        return f'Importación #{self.id} — {self.formulario.nombre} ({self.get_modo_display()})'


class ImportAudit(models.Model):
    TIPOS = [
        ('creacion', 'Creación'),
        ('actualizacion', 'Actualización'),
        ('error', 'Error'),
        ('advertencia', 'Advertencia'),
        ('decision', 'Decisión automática'),
        ('ignorado', 'Ignorado'),
        ('rollback', 'Rollback'),
    ]

    import_log = models.ForeignKey(ImportLog, on_delete=models.CASCADE, related_name='audits')
    tipo = models.CharField(max_length=20, choices=TIPOS, db_index=True)
    registro_id = models.IntegerField(null=True, blank=True)
    campo_nombre = models.CharField(max_length=200, blank=True)
    valor_anterior = models.TextField(blank=True)
    valor_nuevo = models.TextField(blank=True)
    mensaje = models.TextField()
    metadata_json = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Auditoría de importación'
        verbose_name_plural = 'Auditorías de importación'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_tipo_display()}: {self.mensaje[:80]}'


class ImportSnapshot(models.Model):
    import_log = models.ForeignKey(ImportLog, on_delete=models.CASCADE, related_name='snapshots')
    registro = models.ForeignKey(Registro, on_delete=models.CASCADE)
    valores_anteriores = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Snapshot de importación'
        verbose_name_plural = 'Snapshots de importación'
        unique_together = [('import_log', 'registro')]

    def __str__(self):
        return f'Snapshot #{self.registro_id} — Importación #{self.import_log_id}'


class MappingMemory(models.Model):
    """
    Memoria persistente de mapeos de columnas para importaciones.

    Almacena mapeos exitosos para reutilizarlos automáticamente
    en futuras importaciones del mismo formulario con el mismo
    patrón de encabezados.
    """
    formulario = models.ForeignKey(
        Formulario, on_delete=models.CASCADE, related_name='mapping_memories'
    )
    headers_hash = models.CharField(
        max_length=64, db_index=True,
        help_text='SHA256 de los nombres de columna normalizados.',
    )
    headers_text = models.TextField(
        blank=True,
        help_text='JSON con la lista original de encabezados.',
    )
    mapping_json = models.TextField(
        help_text='JSON con el mapeo {col_idx: campo_nombre}.',
    )
    confidence_avg = models.FloatField(
        default=0.95,
        help_text='Confianza promedio del mapeo almacenado.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    times_used = models.IntegerField(
        default=1,
        help_text='Número de veces que este mapeo ha sido reutilizado.',
    )

    class Meta:
        verbose_name = 'Memoria de mapeo'
        verbose_name_plural = 'Memorias de mapeo'
        unique_together = [('formulario', 'headers_hash')]
        ordering = ['-times_used', '-updated_at']

    def __str__(self):
        return f'MappingMemory[{self.formulario.nombre}] hash={self.headers_hash[:12]}'
