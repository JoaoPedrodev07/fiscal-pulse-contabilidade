from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    Equipe da contabilidade: admin (is_staff=True) e operadores (is_staff=False).
    NÃO representa clientes do escritório — isso é fiscal.Cliente.
    """

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'
        ordering = ['username']

    def __str__(self):
        return self.username
