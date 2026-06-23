# Generated manually to add a specific inventory reason for system sales.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('productos', '0004_alter_movimientoinventario_motivo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='movimientoinventario',
            name='motivo',
            field=models.CharField(
                blank=True,
                choices=[
                    ('compra_proveedor', 'Compra a proveedor'),
                    ('devolucion_cliente', 'Devolución de cliente'),
                    ('venta_manual', 'Venta manual'),
                    ('venta_sistema', 'Venta del sistema'),
                    ('producto_danado', 'Producto danado'),
                    ('perdida', 'Pérdida'),
                    ('robo', 'Robo'),
                    ('conteo_fisico', 'Conteo físico'),
                    ('correccion_manual', 'Corrección manual'),
                    ('devolucion_proveedor', 'Devolución a proveedor'),
                ],
                max_length=100,
                null=True,
            ),
        ),
    ]
