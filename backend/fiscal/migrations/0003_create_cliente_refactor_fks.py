import django.db.models.deletion
from django.db import migrations, models


def migrate_clientes(apps, schema_editor):
    """
    Cria um registro em fiscal_cliente para cada usuário não-staff
    referenciado em tabelas fiscais, e preenche os novos FKs (cliente_novo_id).
    Em bancos vazios ou sem usuários em tabelas fiscais, não faz nada.
    """
    User = apps.get_model('users', 'User')
    Cliente = apps.get_model('fiscal', 'Cliente')
    Certificado = apps.get_model('fiscal', 'Certificado')
    ControleNSU = apps.get_model('fiscal', 'ControleNSU')
    Documento = apps.get_model('fiscal', 'Documento')
    LogCaptura = apps.get_model('fiscal', 'LogCaptura')

    # Coleta todos os user_ids referenciados nas tabelas fiscais
    user_ids = set()
    user_ids.update(Certificado.objects.values_list('cliente_id', flat=True))
    user_ids.update(ControleNSU.objects.values_list('cliente_id', flat=True))
    user_ids.update(Documento.objects.values_list('cliente_id', flat=True))
    user_ids.update(LogCaptura.objects.values_list('cliente_id', flat=True))
    user_ids.discard(None)

    # Cria um Cliente para cada User encontrado e armazena o mapeamento
    user_to_cliente = {}
    for user_id in user_ids:
        try:
            user = User.objects.get(pk=user_id)
            # Fallback de CNPJ para não violar o UNIQUE — não deve ocorrer em dados reais
            cnpj = user.cnpj or f'{user_id:014d}'
            cliente, _ = Cliente.objects.get_or_create(
                cnpj=cnpj,
                defaults={
                    'razao_social': user.razao_social or user.username,
                    'telefone': getattr(user, 'telefone', '') or '',
                    'ativo': user.is_active,
                },
            )
            user_to_cliente[user_id] = cliente.pk
        except User.DoesNotExist:
            pass

    # Preenche os novos campos nullable com os IDs de Cliente recém-criados
    for cert in Certificado.objects.all():
        if cert.cliente_id in user_to_cliente:
            cert.cliente_novo_id = user_to_cliente[cert.cliente_id]
            cert.save(update_fields=['cliente_novo_id'])

    for nsu in ControleNSU.objects.all():
        if nsu.cliente_id in user_to_cliente:
            nsu.cliente_novo_id = user_to_cliente[nsu.cliente_id]
            nsu.save(update_fields=['cliente_novo_id'])

    for doc in Documento.objects.all():
        if doc.cliente_id in user_to_cliente:
            doc.cliente_novo_id = user_to_cliente[doc.cliente_id]
            doc.save(update_fields=['cliente_novo_id'])

    for log in LogCaptura.objects.all():
        if log.cliente_id in user_to_cliente:
            log.cliente_novo_id = user_to_cliente[log.cliente_id]
            log.save(update_fields=['cliente_novo_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0002_initial'),
    ]

    operations = [
        # ── 1. Cria o model Cliente ────────────────────────────────────────────
        migrations.CreateModel(
            name='Cliente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cnpj', models.CharField(help_text='Somente dígitos, sem pontuação.', max_length=14, unique=True, verbose_name='CNPJ')),
                ('razao_social', models.CharField(max_length=255, verbose_name='Razão Social')),
                ('telefone', models.CharField(blank=True, max_length=15, verbose_name='Telefone')),
                ('ativo', models.BooleanField(default=True, verbose_name='Ativo')),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Cliente',
                'verbose_name_plural': 'Clientes',
                'ordering': ['razao_social'],
            },
        ),

        # ── 2. Adiciona colunas nullable apontando para fiscal.Cliente ─────────
        migrations.AddField(
            model_name='certificado',
            name='cliente_novo',
            field=models.ForeignKey(
                'fiscal.Cliente',
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='certificados_novo',
                verbose_name='Cliente',
            ),
        ),
        migrations.AddField(
            model_name='controlensu',
            name='cliente_novo',
            field=models.ForeignKey(
                'fiscal.Cliente',
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='controles_nsu_novo',
                verbose_name='Cliente',
            ),
        ),
        migrations.AddField(
            model_name='documento',
            name='cliente_novo',
            field=models.ForeignKey(
                'fiscal.Cliente',
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='documentos_novo',
                verbose_name='Cliente',
            ),
        ),
        migrations.AddField(
            model_name='logcaptura',
            name='cliente_novo',
            field=models.ForeignKey(
                'fiscal.Cliente',
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='logs_captura_novo',
                verbose_name='Cliente',
            ),
        ),

        # ── 3. Migração de dados ───────────────────────────────────────────────
        migrations.RunPython(migrate_clientes, migrations.RunPython.noop),

        # ── 4. Remove unique_together e índice que dependem do FK antigo ───────
        migrations.AlterUniqueTogether(
            name='controlensu',
            unique_together=set(),
        ),
        migrations.RemoveIndex(
            model_name='documento',
            name='doc_cliente_competencia_idx',
        ),

        # ── 5. Remove colunas FK antigas (apontavam para users.User) ──────────
        migrations.RemoveField(model_name='certificado', name='cliente'),
        migrations.RemoveField(model_name='controlensu', name='cliente'),
        migrations.RemoveField(model_name='documento', name='cliente'),
        migrations.RemoveField(model_name='logcaptura', name='cliente'),

        # ── 6. Renomeia as colunas novas para 'cliente' ────────────────────────
        migrations.RenameField(model_name='certificado', old_name='cliente_novo', new_name='cliente'),
        migrations.RenameField(model_name='controlensu', old_name='cliente_novo', new_name='cliente'),
        migrations.RenameField(model_name='documento', old_name='cliente_novo', new_name='cliente'),
        migrations.RenameField(model_name='logcaptura', old_name='cliente_novo', new_name='cliente'),

        # ── 7. Torna os FKs não-nulos e define related_names definitivos ───────
        migrations.AlterField(
            model_name='certificado',
            name='cliente',
            field=models.ForeignKey(
                'fiscal.Cliente',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='certificados',
                verbose_name='Cliente',
            ),
        ),
        migrations.AlterField(
            model_name='controlensu',
            name='cliente',
            field=models.ForeignKey(
                'fiscal.Cliente',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='controles_nsu',
                verbose_name='Cliente',
            ),
        ),
        migrations.AlterField(
            model_name='documento',
            name='cliente',
            field=models.ForeignKey(
                'fiscal.Cliente',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='documentos',
                verbose_name='Cliente',
            ),
        ),
        migrations.AlterField(
            model_name='logcaptura',
            name='cliente',
            field=models.ForeignKey(
                'fiscal.Cliente',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='logs_captura',
                verbose_name='Cliente',
            ),
        ),

        # ── 8. Restaura unique_together e índice com novo FK ──────────────────
        migrations.AlterUniqueTogether(
            name='controlensu',
            unique_together={('cliente', 'tipo_documento')},
        ),
        migrations.AddIndex(
            model_name='documento',
            index=models.Index(fields=['cliente', 'competencia'], name='doc_cliente_competencia_idx'),
        ),

        # ── 9. Corrige max_length de LogCaptura.tipo_documento (5 → 20) ───────
        migrations.AlterField(
            model_name='logcaptura',
            name='tipo_documento',
            field=models.CharField(max_length=20, verbose_name='Tipo de Documento'),
        ),
    ]
