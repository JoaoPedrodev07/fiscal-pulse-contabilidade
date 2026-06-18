from django.db import models


class TipoDocumento(models.TextChoices):
    NFE  = 'NFE',  'NF-e'
    CTE  = 'CTE',  'CT-e'
    NFSE = 'NFSE', 'NFS-e'
    NFCE = 'NFCE', 'NFC-e'


class StatusDocumento(models.TextChoices):
    CAPTURADO   = 'CAPTURADO',   'Capturado'
    MANIFESTADO = 'MANIFESTADO', 'Manifestado'
    COMPLETO    = 'COMPLETO',    'Completo'


class Cliente(models.Model):
    """
    CNPJ da carteira do escritório. NÃO loga no sistema —
    é gerenciado pelos Users (equipe da contabilidade).
    """
    cnpj         = models.CharField(max_length=14, unique=True, verbose_name='CNPJ',
                                    help_text='Somente dígitos, sem pontuação.')
    razao_social = models.CharField(max_length=255, verbose_name='Razão Social')
    telefone     = models.CharField(max_length=15, blank=True, verbose_name='Telefone')
    uf           = models.CharField(max_length=2, default='RJ', verbose_name='UF',
                                    help_text='Sigla do estado (ex: SP, RJ). Usada para roteamento SEFAZ.')
    ativo        = models.BooleanField(default=True, verbose_name='Ativo')
    criado_em    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['razao_social']

    def __str__(self):
        return f'{self.razao_social} ({self.cnpj})'


class Certificado(models.Model):
    # PROTECT: impede exclusão de cliente que ainda tem certificado registrado
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name='certificados',
        verbose_name='Cliente',
    )
    nome_arquivo = models.CharField(max_length=255, verbose_name='Nome do Arquivo')
    validade     = models.DateField(verbose_name='Validade')
    ativo        = models.BooleanField(default=True, verbose_name='Ativo')
    criado_em    = models.DateTimeField(auto_now_add=True)


    conteudo_criptografado = models.BinaryField(
        null=True, 
        blank=True,
        verbose_name='Conteúdo do certificado (.pfx) criptografado em AES'
    )
    
    
    senha_criptografada = models.BinaryField(
        null=True, 
        blank=True,
        verbose_name='Senha do certificado criptografada em AES'
    )
    class Meta:
        verbose_name = 'Certificado'
        verbose_name_plural = 'Certificados'
        ordering = ['cliente', 'validade']

    def __str__(self):
        return f'{self.cliente} — {self.nome_arquivo}'


class ControleNSU(models.Model):
    # CASCADE: controles de NSU não fazem sentido sem o cliente
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='controles_nsu',
        verbose_name='Cliente',
    )
    tipo_documento = models.CharField(
        max_length=5,
        choices=TipoDocumento.choices,
        verbose_name='Tipo de Documento',
    )
    ultimo_nsu    = models.BigIntegerField(default=0, verbose_name='Último NSU')
    max_nsu       = models.BigIntegerField(default=0, verbose_name='Max NSU')
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['cliente', 'tipo_documento']]
        verbose_name = 'Controle NSU'
        verbose_name_plural = 'Controles NSU'
        ordering = ['id']

    def __str__(self):
        return f'{self.cliente} / {self.tipo_documento} — NSU {self.ultimo_nsu}'


class Documento(models.Model):
    # PROTECT: documentos fiscais são auditoria permanente
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name='documentos',
        verbose_name='Cliente',
    )
    # UNIQUE na chave de acesso: reexecução da captura não pode duplicar documento
    chave = models.CharField(
        max_length=44,
        unique=True,
        db_index=True,
        verbose_name='Chave de Acesso',
    )
    tipo_documento = models.CharField(
        max_length=5,
        choices=TipoDocumento.choices,
        verbose_name='Tipo',
    )
    emitente     = models.CharField(max_length=255, verbose_name='Emitente')
    valor        = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='Valor (R$)')
    data_emissao = models.DateField(verbose_name='Data de Emissão')
    # Formato "AAAA-MM" — indexado para consultas de relatório mensal
    competencia  = models.CharField(max_length=7, db_index=True, verbose_name='Competência')
    status = models.CharField(
        max_length=15,
        choices=StatusDocumento.choices,
        default=StatusDocumento.CAPTURADO,
        verbose_name='Status',
    )
    metadados = models.JSONField(default=dict, blank=True, verbose_name='Metadados')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_emissao']
        indexes = [
            models.Index(fields=['cliente', 'competencia'], name='doc_cliente_competencia_idx'),
        ]
        verbose_name = 'Documento'
        verbose_name_plural = 'Documentos'

    def __str__(self):
        return f'{self.tipo_documento} {self.chave[:10]}… — {self.cliente}'


class Xml(models.Model):
    # CASCADE: XML não existe sem o documento pai
    # Tabela separada para não carregar o texto grande nas listagens
    documento = models.OneToOneField(
        Documento,
        on_delete=models.CASCADE,
        related_name='xml',
        verbose_name='Documento',
    )
    conteudo  = models.TextField(verbose_name='Conteúdo XML')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'XML'
        verbose_name_plural = 'XMLs'

    def __str__(self):
        return f'XML de {self.documento}'


class Manifestacao(models.Model):
    CIENCIA         = '210210'
    CONFIRMACAO     = '210200'
    DESCONHECIMENTO = '210220'
    NAO_REALIZADO   = '210240'

    TIPO_EVENTO_CHOICES = [
        (CIENCIA,         'Ciência da Operação'),
        (CONFIRMACAO,     'Confirmação da Operação'),
        (DESCONHECIMENTO, 'Desconhecimento da Operação'),
        (NAO_REALIZADO,   'Operação não Realizada'),
    ]

    documento   = models.OneToOneField(
        Documento,
        on_delete=models.CASCADE,
        related_name='manifestacao',
        verbose_name='Documento',
    )
    tipo_evento = models.CharField(
        max_length=6,
        choices=TIPO_EVENTO_CHOICES,
        default=CIENCIA,
        verbose_name='Tipo de Evento',
    )
    protocolo   = models.CharField(max_length=50, blank=True, verbose_name='Protocolo SEFAZ')
    enviado_em  = models.DateTimeField(auto_now_add=True)
    sucesso     = models.BooleanField(verbose_name='Sucesso')
    mensagem    = models.TextField(blank=True, verbose_name='Mensagem')

    class Meta:
        verbose_name = 'Manifestação'
        verbose_name_plural = 'Manifestações'
        ordering = ['-enviado_em']

    def __str__(self):
        flag = 'OK' if self.sucesso else 'ERRO'
        return f'[{flag}] Manifestação {self.tipo_evento} — {self.documento}'


class LogCaptura(models.Model):
    # CASCADE: logs são registros auxiliares
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='logs_captura',
        verbose_name='Cliente',
    )
    tipo_documento = models.CharField(max_length=20, verbose_name='Tipo de Documento')
    executado_em   = models.DateTimeField(auto_now_add=True)
    sucesso        = models.BooleanField(verbose_name='Sucesso')
    mensagem       = models.TextField(blank=True, verbose_name='Mensagem')

    class Meta:
        ordering = ['-executado_em']
        verbose_name = 'Log de Captura'
        verbose_name_plural = 'Logs de Captura'

    def __str__(self):
        flag = 'OK' if self.sucesso else 'ERRO'
        return f'[{flag}] {self.cliente} / {self.tipo_documento} em {self.executado_em:%Y-%m-%d %H:%M}'
