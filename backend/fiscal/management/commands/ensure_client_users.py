import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Cria ou atualiza usuários de clientes a partir de variáveis de ambiente.'

    def handle(self, *args, **options):
        User = get_user_model()

        # Lê pares CLIENT_USER_1=username:senha:cnpj, CLIENT_USER_2=..., etc.
        i = 1
        while True:
            raw = os.environ.get(f'CLIENT_USER_{i}')
            if not raw:
                break
            parts = raw.split(':')
            if len(parts) != 3:
                self.stdout.write(f'CLIENT_USER_{i} formato inválido (esperado user:senha:cnpj) — pulando.')
                i += 1
                continue

            username, password, cnpj = parts
            self._ensure_user(User, username, password, cnpj)
            i += 1

    def _ensure_user(self, User, username, password, cnpj):
        from fiscal.models import Cliente
        try:
            cliente = Cliente.objects.get(cnpj=cnpj)
        except Cliente.DoesNotExist:
            self.stdout.write(f'Cliente com CNPJ {cnpj} não encontrado — pulando {username}.')
            return

        user, created = User.objects.get_or_create(username=username)
        user.is_staff     = False
        user.is_superuser = False
        user.is_active    = True
        user.cliente      = cliente
        user.set_password(password)
        user.save()

        action = 'criado' if created else 'atualizado'
        self.stdout.write(self.style.SUCCESS(
            f'Usuário "{username}" {action} → {cliente.razao_social} ({cnpj})'
        ))
