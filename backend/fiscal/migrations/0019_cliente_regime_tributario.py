from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0018_alter_documento_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliente',
            name='regime_tributario',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Não informado'),
                    ('MEI', 'MEI — Microempreendedor Individual'),
                    ('SN', 'Simples Nacional'),
                    ('LP', 'Lucro Presumido'),
                    ('LR', 'Lucro Real'),
                    ('LA', 'Lucro Arbitrado'),
                ],
                default='',
                max_length=3,
                verbose_name='Regime Tributário',
            ),
        ),
    ]
