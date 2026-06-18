from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0007_manifestacao'),
    ]

    operations = [
        migrations.AlterField(
            model_name='documento',
            name='status',
            field=models.CharField(
                choices=[
                    ('CAPTURADO',   'Capturado'),
                    ('MANIFESTADO', 'Manifestado'),
                    ('COMPLETO',    'Completo'),
                    ('CANCELADO',   'Cancelado'),
                ],
                default='CAPTURADO',
                max_length=15,
                verbose_name='Status',
            ),
        ),
    ]
