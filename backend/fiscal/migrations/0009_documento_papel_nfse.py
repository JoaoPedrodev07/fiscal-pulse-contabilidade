from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0008_alter_documento_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='documento',
            name='papel_nfse',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='EMITENTE (receita) ou TOMADOR (despesa). Preenchido apenas para NFS-e.',
                max_length=10,
                verbose_name='Papel NFS-e',
            ),
        ),
    ]
