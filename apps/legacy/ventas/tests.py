from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from productos.models import Categoria, MovimientoInventario, Producto
from .models import Venta


class VentaModelTests(TestCase):
    def setUp(self):
        self.vendedor = User.objects.create_user(
            username='vendedor1',
            password='clave-segura-123'
        )
        self.categoria = Categoria.objects.create(nombre='Blusas')
        self.producto = Producto.objects.create(
            nombre='Blusa lino',
            categoria=self.categoria,
            talla='M',
            color='Azul',
            precio=Decimal('29990.00'),
            stock=10,
        )

    def test_registrar_venta_descuenta_stock_y_crea_movimiento(self):
        venta = Venta.objects.create(
            producto=self.producto,
            vendedor=self.vendedor,
            cantidad=3,
        )

        self.producto.refresh_from_db()

        self.assertEqual(self.producto.stock, 7)
        self.assertEqual(venta.total, Decimal('89970.00'))

        movimiento = MovimientoInventario.objects.get(producto=self.producto)
        self.assertEqual(movimiento.tipo, 'salida')
        self.assertEqual(movimiento.motivo, 'venta_sistema')
        self.assertEqual(movimiento.cantidad, 3)
        self.assertEqual(movimiento.stock_anterior, 10)
        self.assertEqual(movimiento.stock_nuevo, 7)

    def test_no_permite_venta_sin_stock_suficiente(self):
        with self.assertRaises(ValueError):
            Venta.objects.create(
                producto=self.producto,
                vendedor=self.vendedor,
                cantidad=11,
            )

        self.producto.refresh_from_db()

        self.assertEqual(self.producto.stock, 10)
        self.assertEqual(Venta.objects.count(), 0)
        self.assertEqual(MovimientoInventario.objects.count(), 0)

    def test_producto_con_ventas_no_se_elimina(self):
        Venta.objects.create(
            producto=self.producto,
            vendedor=self.vendedor,
            cantidad=1,
        )

        with self.assertRaises(ProtectedError):
            self.producto.delete()

        self.assertTrue(Producto.objects.filter(pk=self.producto.pk).exists())
        self.assertEqual(Venta.objects.count(), 1)
