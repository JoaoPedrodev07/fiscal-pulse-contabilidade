from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0006_cliente_uf'),
    ]

    operations = [
        migrations.CreateModel(
            name='Manifestacao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo_evento', models.CharField(
                    choices=[
                        ('210210', 'Ciência da Operação'),
                        ('210200', 'Confirmação da Operação'),
                        ('210220', 'Desconhecimento da Operação'),
                        ('210240', 'Operação não Realizada'),
                    ],
                    default='210210',
                    max_length=6,
                    verbose_name='Tipo de Evento',
                )),
                ('protocolo', models.CharField(blank=True, max_length=50, verbose_name='Protocolo SEFAZ')),
                ('enviado_em', models.DateTimeField(auto_now_add=True)),
                ('sucesso', models.BooleanField(verbose_name='Sucesso')),
                ('mensagem', models.TextField(blank=True, verbose_name='Mensagem')),
                ('documento', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='manifestacao',
                    to='fiscal.documento',
                    verbose_name='Documento',
                )),
            ],
            options={
                'verbose_name': 'Manifestação',
                'verbose_name_plural': 'Manifestações',
                'ordering': ['-enviado_em'],
            },
        ),
    ]
