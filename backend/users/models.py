from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    Equipe da contabilidade: is_staff=True vê tudo.
    Cliente final: is_staff=False + cliente FK → vê só os próprios documentos.
    """
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
