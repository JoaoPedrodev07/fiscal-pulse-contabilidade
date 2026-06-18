from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0005_alter_controlensu_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliente',
            name='uf',
            field=models.CharField(
                default='RJ',
                max_length=2,
                verbose_name='UF',
                help_text='Sigla do estado (ex: SP, RJ). Usada para roteamento SEFAZ.',
            ),
        ),
    ]
