from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ventas', '0006_cliente_activo'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliente',
            name='apellido',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
