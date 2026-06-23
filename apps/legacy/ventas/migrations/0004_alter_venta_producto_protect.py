# Generated manually to preserve sales history when products exist in sales.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('productos', '0005_alter_movimientoinventario_motivo'),
        ('ventas', '0003_fix_venta_related_name_and_quantity'),
    ]

    operations = [
        migrations.AlterField(
            model_name='venta',
            name='producto',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='ventas',
                to='productos.producto',
            ),
        ),
    ]
