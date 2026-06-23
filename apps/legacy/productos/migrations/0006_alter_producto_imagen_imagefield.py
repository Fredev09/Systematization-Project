# Generated manually to store product images as uploaded files instead of URLs.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('productos', '0005_alter_movimientoinventario_motivo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='producto',
            name='imagen',
            field=models.ImageField(blank=True, max_length=255, null=True, upload_to='productos/'),
        ),
    ]
