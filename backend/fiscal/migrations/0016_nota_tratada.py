from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0015_log_auditoria_nsu'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotaTratada',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero_nfse',        models.CharField(blank=True, max_length=20,  verbose_name='Número NFSe')),
                ('data_competencia',   models.CharField(blank=True, max_length=7,   verbose_name='Competência (MM/AAAA)')),
                ('data_processamento', models.CharField(blank=True, max_length=10,  verbose_name='Data Processamento')),
                ('emitente_cnpj',      models.CharField(blank=True, db_index=True, max_length=14, verbose_name='CNPJ Emitente')),
                ('emitente_nome',      models.CharField(blank=True, max_length=255, verbose_name='Emitente Nome')),
                ('tomador_doc',        models.CharField(blank=True, max_length=14,  verbose_name='CNPJ/CPF Tomador')),
                ('tomador_nome',       models.CharField(blank=True, max_length=255, verbose_name='Tomador Nome')),
                ('codigo_tributo',     models.CharField(blank=True, max_length=20,  verbose_name='Código Tributo Nacional')),
                ('descricao_servico',  models.TextField(blank=True,                 verbose_name='Descrição do Serviço')),
                ('regime_trib',        models.CharField(blank=True, max_length=80,  verbose_name='Regime Especial Tributação')),
                ('valor_servico',      models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Valor Serviço (R$)')),
                ('valor_liquido',      models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Valor Líquido (R$)')),
                ('ret_pis',            models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Ret. PIS (R$)')),
                ('ret_cofins',         models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Ret. COFINS (R$)')),
                ('ret_csll',           models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Ret. CSLL (R$)')),
                ('ret_irrf',           models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Ret. IRRF (R$)')),
                ('ret_inss',           models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Ret. INSS (R$)')),
                ('parecer',            models.CharField(max_length=50, choices=[('Válida', 'Válida'), ('Válida (DIVERGÊNCIA RETENÇÃO)', 'Válida (Divergência de Retenção)'), ('Cancelada', 'Cancelada'), ('Substituída', 'Substituída')], verbose_name='Parecer Fiscal')),
                ('chave_substituta',   models.CharField(blank=True, max_length=50,  verbose_name='Chave Substituta')),
                ('processado_em',      models.DateTimeField(auto_now_add=True)),
                ('documento', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='nota_tratada',
                    to='fiscal.documento',
                    verbose_name='Documento',
                )),
            ],
            options={
                'verbose_name': 'Nota Tratada',
                'verbose_name_plural': 'Notas Tratadas',
                'ordering': ['-processado_em'],
            },
        ),
        migrations.AddIndex(
            model_name='notatratada',
            index=models.Index(fields=['emitente_cnpj', 'data_competencia'], name='nota_trat_cnpj_comp_idx'),
        ),
    ]
