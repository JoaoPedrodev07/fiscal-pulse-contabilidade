import decimal
import datetime
from django.core.management.base import BaseCommand
from fiscal.models import Cliente, Certificado, ControleNSU, Documento, Xml, TipoDocumento, StatusDocumento

CLIENTES_FAKE = [
    {
        'cnpj':         '12345678000195',
        'razao_social': 'Padaria do Joao Ltda',
        'telefone':     '11999990001',
    },
    {
        'cnpj':         '98765432000110',
        'razao_social': 'Distribuidora Silva e Filhos SA',
        'telefone':     '11999990002',
    },
    {
        'cnpj':         '11223344000180',
        'razao_social': 'Tech Solucoes ME',
        'telefone':     '11999990003',
    },
]

# (cnpj_cliente, chave, tipo, emitente, valor, data_emissao, competencia, status)
DOCUMENTOS_FAKE = [
    ('12345678000195', '35240112345678000195550010000000011234567890', TipoDocumento.NFE,
     'Fornecedor ABC Ltda', '1250.00', '2024-01-10', '2024-01', StatusDocumento.COMPLETO),
    ('12345678000195', '35240212345678000195550010000000021234567891', TipoDocumento.NFE,
     'Distribuidora XYZ SA', '3400.50', '2024-02-15', '2024-02', StatusDocumento.COMPLETO),
    ('12345678000195', '35240312345678000195570010000000031234567892', TipoDocumento.NFSE,
     'Consultoria Omega Ltda', '800.00', '2024-03-05', '2024-03', StatusDocumento.CAPTURADO),
    ('98765432000110', '35240198765432000110550010000000041234567893', TipoDocumento.NFE,
     'Importadora Delta SA', '12500.00', '2024-01-20', '2024-01', StatusDocumento.MANIFESTADO),
    ('98765432000110', '35240298765432000110550010000000051234567894', TipoDocumento.NFE,
     'Exportadora Beta Ltda', '7890.75', '2024-02-28', '2024-02', StatusDocumento.COMPLETO),
    ('98765432000110', '57240198765432000110570030000000061234567895', TipoDocumento.CTE,
     'Transportadora Rapida SA', '450.00', '2024-03-12', '2024-03', StatusDocumento.COMPLETO),
    ('11223344000180', '35240111223344000180550010000000071234567896', TipoDocumento.NFE,
     'Tech Parts Ltda', '2200.00', '2024-01-08', '2024-01', StatusDocumento.COMPLETO),
    ('11223344000180', '35240211223344000180650010000000081234567897', TipoDocumento.NFCE,
     'Loja Virtual ME', '150.90', '2024-02-03', '2024-02', StatusDocumento.CAPTURADO),
    ('11223344000180', '35240311223344000180550010000000091234567898', TipoDocumento.NFE,
     'Suprimentos Gerais SA', '5600.00', '2024-03-22', '2024-03', StatusDocumento.MANIFESTADO),
    ('12345678000195', '35240412345678000195550010000000101234567899', TipoDocumento.NFE,
     'Atacadao do Norte Ltda', '980.30', '2024-04-18', '2024-04', StatusDocumento.CAPTURADO),
]

XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe{chave}" versao="4.00">
      <ide><cNF>12345678</cNF><natOp>VENDA</natOp><mod>55</mod></ide>
      <emit><CNPJ>{cnpj_cliente}</CNPJ><xNome>{emitente}</xNome></emit>
      <total><ICMSTot><vNF>{valor}</vNF></ICMSTot></total>
    </infNFe>
  </NFe>
</nfeProc>"""


class Command(BaseCommand):
    help = 'Popula o banco com clientes fiscais e documentos de teste'

    def handle(self, *args, **kwargs):
        criados = {'clientes': 0, 'docs': 0, 'xmls': 0}

        for dados in CLIENTES_FAKE:
            cliente, created = Cliente.objects.get_or_create(
                cnpj=dados['cnpj'],
                defaults={
                    'razao_social': dados['razao_social'],
                    'telefone':     dados['telefone'],
                },
            )
            if created:
                criados['clientes'] += 1
                Certificado.objects.create(
                    cliente=cliente,
                    nome_arquivo=f"certificado_{dados['cnpj']}.pfx",
                    validade=datetime.date(2026, 12, 31),
                )
                for tipo in TipoDocumento:
                    ControleNSU.objects.get_or_create(
                        cliente=cliente,
                        tipo_documento=tipo,
                        defaults={'ultimo_nsu': 0, 'max_nsu': 0},
                    )

        for (cnpj, chave, tipo, emitente, valor, data_str, competencia, status_doc) in DOCUMENTOS_FAKE:
            cliente = Cliente.objects.get(cnpj=cnpj)
            doc, created = Documento.objects.get_or_create(
                chave=chave,
                defaults={
                    'cliente':        cliente,
                    'tipo_documento': tipo,
                    'emitente':       emitente,
                    'valor':          decimal.Decimal(valor),
                    'data_emissao':   datetime.date.fromisoformat(data_str),
                    'competencia':    competencia,
                    'status':         status_doc,
                },
            )
            if created:
                criados['docs'] += 1
                if tipo in (TipoDocumento.NFE, TipoDocumento.CTE):
                    xml_conteudo = XML_TEMPLATE.format(
                        chave=chave,
                        cnpj_cliente=cnpj,
                        emitente=emitente,
                        valor=valor,
                    )
                    Xml.objects.get_or_create(documento=doc, defaults={'conteudo': xml_conteudo})
                    criados['xmls'] += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seed concluido: {criados['clientes']} cliente(s), "
            f"{criados['docs']} documento(s), {criados['xmls']} XML(s) criados."
        ))
