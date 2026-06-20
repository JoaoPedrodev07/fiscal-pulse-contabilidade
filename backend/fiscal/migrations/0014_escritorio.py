import django.db.models.deletion
from django.db import migrations, models


def criar_escritorio_padrao_e_vincular(apps, schema_editor):
    """
    Cria um Escritório padrão e vincula todos os Clientes existentes a ele.
    O CNPJ '00000000000001' é um placeholder — deve ser atualizado pelo admin.
    """
    Escritorio = apps.get_model('fiscal', 'Escritorio')
    Cliente = apps.get_model('fiscal', 'Cliente')

    escritorio, _ = Escritorio.objects.get_or_create(
        cnpj='00000000000001',
        defaults={'razao_social': 'ESCRITÓRIO PADRÃO', 'ativo': True},
    )
    Cliente.objects.filter(escritorio__isnull=True).update(escritorio=escritorio)


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0013_backfill_papel_nfse'),
    ]

    operations = [
        migrations.CreateModel(
            name='Escritorio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('razao_social', models.CharField(max_length=255, verbose_name='Razão Social')),
                ('cnpj', models.CharField(
                    help_text='CNPJ do próprio escritório de contabilidade, sem pontuação.',
                    max_length=14, unique=True, verbose_name='CNPJ',
                )),
                ('ativo', models.BooleanField(default=True, verbose_name='Ativo')),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Escritório',
                'verbose_name_plural': 'Escritórios',
                'ordering': ['razao_social'],
            },
        ),
        migrations.AddField(
            model_name='cliente',
            name='escritorio',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='clientes',
                to='fiscal.escritorio',
                verbose_name='Escritório',
            ),
        ),
        migrations.RunPython(
            criar_escritorio_padrao_e_vincular,
            migrations.RunPython.noop,
        ),
    ]
