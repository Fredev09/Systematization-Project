from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .models import Categoria, MovimientoInventario, Producto


class ProductoModelTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre='Vestidos')

    def test_crear_producto_con_imagen_subida(self):
        imagen = SimpleUploadedFile(
            'vestido.jpg',
            b'contenido-de-prueba',
            content_type='image/jpeg'
        )

        producto = Producto.objects.create(
            nombre='Vestido floral',
            categoria=self.categoria,
            talla='M',
            color='Rosado',
            precio=Decimal('85000.00'),
            stock=12,
            imagen=imagen,
        )

        self.assertEqual(str(producto), 'Vestido floral')
        self.assertEqual(producto.stock, 12)
        self.assertTrue(producto.imagen.name.startswith('productos/'))

    def test_movimiento_inventario_guarda_stock_anterior_y_nuevo(self):
        producto = Producto.objects.create(
            nombre='Blusa básica',
            categoria=self.categoria,
            talla='S',
            color='Blanco',
            precio=Decimal('40000.00'),
            stock=5,
        )

        movimiento = MovimientoInventario.objects.create(
            producto=producto,
            tipo='entrada',
            motivo='compra_proveedor',
            cantidad=3,
            stock_anterior=5,
            stock_nuevo=8,
        )

        self.assertEqual(str(movimiento), 'Blusa básica - entrada - 3')
        self.assertEqual(movimiento.stock_anterior, 5)
        self.assertEqual(movimiento.stock_nuevo, 8)
