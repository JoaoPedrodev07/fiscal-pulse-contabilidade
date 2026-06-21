from django.db import models


class Escritorio(models.Model):
    """
    Tenant raiz do sistema. Cada escritório de contabilidade é um Escritorio.
    Todos os Clientes (CNPJs da carteira) e Usuários pertencem a um Escritorio.
    Superusuários (is_superuser=True) ficam com escritorio=None e veem tudo.
    """
    razao_social = models.CharField(max_length=255, verbose_name='Razão Social')
    cnpj         = models.CharField(
        max_length=14, unique=True, verbose_name='CNPJ',
        help_text='CNPJ do próprio escritório de contabilidade, sem pontuação.',
    )
    ativo     = models.BooleanField(default=True, verbose_name='Ativo')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Escritório'
        verbose_name_plural = 'Escritórios'
        ordering = ['razao_social']

    def __str__(self):
        return f'{self.razao_social} ({self.cnpj})'


class TipoDocumento(models.TextChoices):
    NFE  = 'NFE',  'NF-e'
    CTE  = 'CTE',  'CT-e'
    NFSE = 'NFSE', 'NFS-e'
    NFCE = 'NFCE', 'NFC-e'


class StatusDocumento(models.TextChoices):
    CAPTURADO   = 'CAPTURADO',   'Capturado'
    MANIFESTADO = 'MANIFESTADO', 'Manifestado'
    COMPLETO    = 'COMPLETO',    'Completo'
    CANCELADO   = 'CANCELADO',   'Cancelado'
    SUBSTITUIDO = 'SUBSTITUIDO', 'Substituído'


class Cliente(models.Model):
    """
    CNPJ da carteira de um Escritorio. NÃO loga no sistema —
    é gerenciado pelos Users (equipe da contabilidade).
    """
    escritorio = models.ForeignKey(
        Escritorio,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='clientes',
        verbose_name='Escritório',
    )
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
        max_length=50,  # NF-e=44 digitos, NFS-e Nacional=50 digitos
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
    papel_nfse = models.CharField(
        max_length=10,
        blank=True,
        default='',
        db_index=True,
        verbose_name='Papel NFS-e',
        help_text='EMITENTE (receita) ou TOMADOR (despesa). Preenchido apenas para NFS-e.',
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


class ResultadoNSU(models.TextChoices):
    SALVO             = 'SALVO',             'Documento salvo'
    DUPLICADO         = 'DUPLICADO',         'Duplicado (já existia)'
    CHAVE_INVALIDA    = 'CHAVE_INVALIDA',    'Chave inválida'
    XML_VAZIO         = 'XML_VAZIO',         'XML vazio'
    XML_INVALIDO      = 'XML_INVALIDO',      'XML indecodificável'
    ERRO_PERSISTENCIA = 'ERRO_PERSISTENCIA', 'Erro ao persistir'


class LogAuditoriaNSU(models.Model):
    """
    Rastrea o destino de cada NSU retornado pelo ADN.
    Permite ao contador verificar por que um NSU específico não gerou documento.
    """
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='logs_auditoria_nsu',
        verbose_name='Cliente',
    )
    tipo_documento = models.CharField(
        max_length=5,
        choices=TipoDocumento.choices,
        verbose_name='Tipo de Documento',
    )
    nsu      = models.BigIntegerField(verbose_name='NSU')
    resultado = models.CharField(
        max_length=20,
        choices=ResultadoNSU.choices,
        verbose_name='Resultado',
    )
    chave       = models.CharField(max_length=50, blank=True, verbose_name='Chave de Acesso')
    executado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-executado_em', 'nsu']
        indexes = [
            models.Index(fields=['cliente', 'tipo_documento'], name='audit_nsu_cliente_tipo_idx'),
        ]
        verbose_name = 'Log de Auditoria NSU'
        verbose_name_plural = 'Logs de Auditoria NSU'

    def __str__(self):
        return f'{self.cliente} / {self.tipo_documento} NSU {self.nsu} → {self.resultado}'


class NotaTratada(models.Model):
    """
    Dados fiscais estruturados extraídos do XML de uma NFS-e.
    Criada automaticamente pelo conector após salvar o XML.
    É a fonte de dados para relatórios, pareceres e exportação em planilha.
    """
    PARECER_CHOICES = [
        ('Válida',                      'Válida'),
        ('Válida (DIVERGÊNCIA RETENÇÃO)', 'Válida (Divergência de Retenção)'),
        ('Cancelada',                   'Cancelada'),
        ('Substituída',                 'Substituída'),
    ]

    documento = models.OneToOneField(
        Documento,
        on_delete=models.CASCADE,
        related_name='nota_tratada',
        verbose_name='Documento',
    )
    numero_nfse        = models.CharField(max_length=20,  blank=True, verbose_name='Número NFSe')
    data_competencia   = models.CharField(max_length=7,   blank=True, verbose_name='Competência (MM/AAAA)')
    data_processamento = models.CharField(max_length=10,  blank=True, verbose_name='Data Processamento')
    emitente_cnpj      = models.CharField(max_length=14,  blank=True, db_index=True, verbose_name='CNPJ Emitente')
    emitente_nome      = models.CharField(max_length=255, blank=True, verbose_name='Emitente Nome')
    tomador_doc        = models.CharField(max_length=14,  blank=True, verbose_name='CNPJ/CPF Tomador')
    tomador_nome       = models.CharField(max_length=255, blank=True, verbose_name='Tomador Nome')
    codigo_tributo     = models.CharField(max_length=20,  blank=True, verbose_name='Código Tributo Nacional')
    descricao_servico  = models.TextField(blank=True,                 verbose_name='Descrição do Serviço')
    regime_trib        = models.CharField(max_length=80,  blank=True, verbose_name='Regime Especial Tributação')
    valor_servico      = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='Valor Serviço (R$)')
    valor_liquido      = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='Valor Líquido (R$)')
    ret_pis            = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='Ret. PIS (R$)')
    ret_cofins         = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='Ret. COFINS (R$)')
    ret_csll           = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='Ret. CSLL (R$)')
    ret_irrf           = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='Ret. IRRF (R$)')
    ret_inss           = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='Ret. INSS (R$)')
    parecer            = models.CharField(max_length=50, choices=PARECER_CHOICES, verbose_name='Parecer Fiscal')
    # Chave da nota que SUBSTITUIU esta (preenchida quando esta nota é marcada como Substituída)
    chave_substituta   = models.CharField(max_length=50, blank=True, verbose_name='Chave Substituta')
    processado_em      = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Nota Tratada'
        verbose_name_plural = 'Notas Tratadas'
        indexes = [
            models.Index(fields=['emitente_cnpj', 'data_competencia'], name='nota_trat_cnpj_comp_idx'),
        ]
        ordering = ['-processado_em']

    def __str__(self):
        return f'NotaTratada {self.numero_nfse} — {self.emitente_cnpj} [{self.parecer}]'
