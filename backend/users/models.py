from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    Superusuário (is_superuser=True, escritorio=None): vê todos os escritórios.
    Staff do escritório (is_staff=True, escritorio=<id>): vê todos os clientes do seu escritório.
    Usuário final (is_staff=False, escritorio=<id>, cliente=<id>): vê só seu próprio CNPJ.
    """
    escritorio = models.ForeignKey(
        'fiscal.Escritorio',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='usuarios',
        verbose_name='Escritório',
        help_text='Escritório de contabilidade ao qual este usuário pertence. Null para superadmin.',
    )
    cliente = models.ForeignKey(
        'fiscal.Cliente',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='usuarios',
        help_text='Vínculo ao CNPJ — preencher para usuários não-staff (clientes finais).',
    )

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'
        ordering = ['username']

    def __str__(self):
        return self.username
