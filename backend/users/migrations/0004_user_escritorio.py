import django.db.models.deletion
from django.db import migrations, models


def vincular_usuarios_ao_escritorio(apps, schema_editor):
    """
    Vincula todos os usuários não-superusuário ao Escritório padrão.
    Superusuários ficam com escritorio=None (veem tudo).
    """
    User = apps.get_model('users', 'User')
    Escritorio = apps.get_model('fiscal', 'Escritorio')

    escritorio = Escritorio.objects.first()
    if not escritorio:
        return

    User.objects.filter(is_superuser=False, escritorio__isnull=True).update(
        escritorio=escritorio,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0014_escritorio'),
        ('users', '0003_add_cliente_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='escritorio',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='usuarios',
                to='fiscal.escritorio',
                verbose_name='Escritório',
                help_text='Escritório de contabilidade ao qual este usuário pertence. Null para superadmin.',
            ),
        ),
        migrations.RunPython(
            vincular_usuarios_ao_escritorio,
            migrations.RunPython.noop,
        ),
    ]
