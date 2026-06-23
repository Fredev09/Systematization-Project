# Generated manually to keep the database schema in sync with the corrected models.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ventas', '0002_alter_venta_producto'),
    ]

    operations = [
        migrations.AlterField(
            model_name='venta',
            name='cantidad',
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name='venta',
            name='producto',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ventas', to='productos.producto'),
        ),
    ]
