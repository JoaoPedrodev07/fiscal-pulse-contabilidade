from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0016_nota_tratada'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='documento',
            index=models.Index(
                fields=['cliente', 'tipo_documento'],
                name='doc_cliente_tipo_idx',
            ),
        ),
    ]
