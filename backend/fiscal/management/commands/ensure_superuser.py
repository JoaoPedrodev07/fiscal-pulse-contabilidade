import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Cria ou atualiza superusuário a partir de variáveis de ambiente.'

    def handle(self, *args, **options):
        User = get_user_model()

        username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
        email    = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

        if not username or not password:
            self.stdout.write(
                'DJANGO_SUPERUSER_USERNAME ou DJANGO_SUPERUSER_PASSWORD não definidos — pulando.'
            )
            return

        user, created = User.objects.get_or_create(username=username)
        user.email        = email
        user.is_staff     = True
        user.is_superuser = True
        user.is_active    = True
        user.set_password(password)
        user.save()

        action = 'criado' if created else 'atualizado'
        self.stdout.write(self.style.SUCCESS(f'Superusuário "{username}" {action} com sucesso.'))
