import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0014_escritorio'),
    ]

    operations = [
        migrations.CreateModel(
            name='LogAuditoriaNSU',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo_documento', models.CharField(
                    choices=[('NFE', 'NF-e'), ('CTE', 'CT-e'), ('NFSE', 'NFS-e'), ('NFCE', 'NFC-e')],
                    max_length=5,
                    verbose_name='Tipo de Documento',
                )),
                ('nsu', models.BigIntegerField(verbose_name='NSU')),
                ('resultado', models.CharField(
                    choices=[
                        ('SALVO', 'Documento salvo'),
                        ('DUPLICADO', 'Duplicado (já existia)'),
                        ('CHAVE_INVALIDA', 'Chave inválida'),
                        ('XML_VAZIO', 'XML vazio'),
                        ('XML_INVALIDO', 'XML indecodificável'),
                        ('ERRO_PERSISTENCIA', 'Erro ao persistir'),
                    ],
                    max_length=20,
                    verbose_name='Resultado',
                )),
                ('chave', models.CharField(blank=True, max_length=50, verbose_name='Chave de Acesso')),
                ('executado_em', models.DateTimeField(auto_now_add=True)),
                ('cliente', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='logs_auditoria_nsu',
                    to='fiscal.cliente',
                    verbose_name='Cliente',
                )),
            ],
            options={
                'verbose_name': 'Log de Auditoria NSU',
                'verbose_name_plural': 'Logs de Auditoria NSU',
                'ordering': ['-executado_em', 'nsu'],
            },
        ),
        migrations.AddIndex(
            model_name='logauditoriansu',
            index=models.Index(
                fields=['cliente', 'tipo_documento'],
                name='audit_nsu_cliente_tipo_idx',
            ),
        ),
    ]
