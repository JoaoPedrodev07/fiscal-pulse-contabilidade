import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Cria superusuário a partir de variáveis de ambiente se ainda não existir.'

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

        if User.objects.filter(username=username).exists():
            self.stdout.write(f'Superusuário "{username}" já existe — nada a fazer.')
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Superusuário "{username}" criado com sucesso.'))
