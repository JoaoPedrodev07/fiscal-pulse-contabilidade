from django.db import migrations


class Migration(migrations.Migration):
    """
    Remove cnpj, razao_social e telefone do model User.
    Esses campos migraram para fiscal.Cliente.
    Depende de fiscal/0003 (que já fez a cópia dos dados para Cliente).
    """

    dependencies = [
        ('users', '0001_initial'),
        ('fiscal', '0003_create_cliente_refactor_fks'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='user',
            options={
                'ordering': ['username'],
                'verbose_name': 'Usuário',
                'verbose_name_plural': 'Usuários',
            },
        ),
        migrations.RemoveField(model_name='user', name='cnpj'),
        migrations.RemoveField(model_name='user', name='razao_social'),
        migrations.RemoveField(model_name='user', name='telefone'),
    ]
