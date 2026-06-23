from django.db import models


class Categoria(models.Model):
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    talla = models.CharField(max_length=20)
    color = models.CharField(max_length=50)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField()
    imagen = models.ImageField(upload_to='productos/', max_length=255, blank=True, null=True)
    imagen_url = models.URLField(max_length=500, blank=True, null=True)

    @property
    def imagen_final_url(self):
        if self.imagen_url:
            return self.imagen_url

        if self.imagen:
            try:
                return self.imagen.url
            except ValueError:
                return ''

        return ''

    @property
    def tiene_imagen(self):
        return bool(self.imagen_final_url)

    def __str__(self):
        return self.nombre


class MovimientoInventario(models.Model):
    tipoElecciones = [
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
        ('correccion', 'Correccion de stock'),
    ]

    motivoElecciones = [
        ('compra_proveedor', 'Compra a proveedor'),
        ('devolucion_cliente', 'Devolucion de cliente'),
        ('venta_manual', 'Venta manual'),
        ('venta_sistema', 'Venta del sistema'),
        ('producto_danado', 'Producto danado'),
        ('perdida', 'Perdida'),
        ('robo', 'Robo'),
        ('conteo_fisico', 'Conteo fisico'),
        ('correccion_manual', 'Correccion manual'),
        ('devolucion_proveedor', 'Devolucion a proveedor'),
    ]

    producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE,
        related_name='movimientos'
    )
    tipo = models.CharField(max_length=15, choices=tipoElecciones)
    motivo = models.CharField(max_length=100, choices=motivoElecciones, blank=True, null=True)
    cantidad = models.PositiveIntegerField()
    stock_anterior = models.PositiveIntegerField()
    stock_nuevo = models.PositiveIntegerField()
    observacion = models.TextField(blank=True, null=True)
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.producto.nombre} - {self.tipo} - {self.cantidad}'