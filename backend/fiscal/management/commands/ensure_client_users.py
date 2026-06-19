import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Cria ou atualiza usuários de clientes a partir de variáveis de ambiente.'

    def handle(self, *args, **options):
        User = get_user_model()

        # Formato: CLIENT_USER_N=username:senha:cnpj[:razao_social]
        # Se razao_social for fornecida e o Cliente não existir, ele é criado.
        i = 1
        while True:
            raw = os.environ.get(f'CLIENT_USER_{i}')
            if not raw:
                break
            parts = raw.split(':')
            if len(parts) < 3:
                self.stdout.write(f'CLIENT_USER_{i} formato inválido (esperado user:senha:cnpj[:razao]) — pulando.')
                i += 1
                continue

            username   = parts[0]
            password   = parts[1]
            cnpj       = parts[2]
            razao      = parts[3] if len(parts) >= 4 else None

            self._ensure_user(User, username, password, cnpj, razao)
            i += 1

    def _ensure_user(self, User, username, password, cnpj, razao_social=None):
        from fiscal.models import Cliente

        try:
            cliente = Cliente.objects.get(cnpj=cnpj)
        except Cliente.DoesNotExist:
            if not razao_social:
                self.stdout.write(
                    self.style.WARNING(
                        f'Cliente CNPJ {cnpj} não encontrado e razao_social não fornecida — pulando {username}.'
                    )
                )
                return
            cliente = Cliente.objects.create(
                cnpj=cnpj,
                razao_social=razao_social,
                ativo=True,
            )
            self.stdout.write(self.style.SUCCESS(
                f'Cliente "{razao_social}" ({cnpj}) criado automaticamente.'
            ))

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
