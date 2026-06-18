"""
Serviço de captura NFS-e Nacional — API ADN (REST + mTLS).

Domínios Oficiais (NT 008/2026):
  Homologação: https://adn.producaorestrita.nfse.gov.br/contribuintes
  Produção:    https://adn.nfse.gov.br/contribuintes

Métodos documentados para Contribuintes:
  GET /nfse/{chaveAcesso}   — Busca nota pela Chave de Acesso (Item 1.3.2)
  GET /dps/{id}             — Recupera chave a partir do ID da DPS (Item 1.4.2)
"""
import base64
import gzip
import json
import logging
import os
import xml.etree.ElementTree as ET

from django.utils import timezone
from fiscal.models import ControleNSU, Documento, Xml

logger = logging.getLogger(__name__)

_ADN_BASE_URL_HOMOLOG = 'https://adn.producaorestrita.nfse.gov.br/contribuintes'
_ADN_BASE_URL_PROD = 'https://adn.nfse.gov.br/contribuintes'


class NFSeADNCapturaService:
    """
    Captura NFS-e via API REST do ADN Nacional.
    Adaptado para conformidade com o Manual do Contribuinte (NT 008/2026).
    """

    def __init__(self, conector_sefaz, cliente):
        self.con = conector_sefaz
        self.cliente = cliente
        self.homologacao = os.environ.get('SEFAZ_HOMOLOGACAO', 'True') != 'False'

    def _descompactar(self, conteudo_b64: str) -> str | None:
        if not conteudo_b64:
            return None
        try:
            padding = len(conteudo_b64) % 4
            if padding:
                conteudo_b64 += '=' * (4 - padding)
            return gzip.decompress(base64.b64decode(conteudo_b64)).decode('utf-8')
        except Exception as e:
            logger.error(f"Erro ao descompactar NFS-e: {e}")
            return None

    def _persistir(self, xml_puro: str, chave: str, emitente: str, valor: float):
        try:
            documento, criado = Documento.objects.get_or_create(
                chave=chave,
                defaults={
                    'cliente': self.cliente,
                    'tipo_documento': 'NFSE',
                    'emitente': emitente,
                    'valor': valor,
                    'data_emissao': timezone.now().date(),
                    'competencia': timezone.now().strftime('%Y-%m'),
                    'status': 'COMPLETO',  # NFS-e é definitiva, não tem manifesto de frete/ciência
                },
            )
            if criado or not hasattr(documento, 'xml'):
                Xml.objects.get_or_create(documento=documento, defaults={'conteudo': xml_puro})
        except Exception as e:
            logger.error(f"Erro ao persistir NFS-e chave {chave[:10]}…: {e}")

    def capturar_proximo_lote(self) -> str:
        """
        Interfere no loop do Celery (tasks.py). Como o barramento nacional
        exige Chave de Acesso para Contribuintes (não há fila pública de NSU),
        o serviço registra a impossibilidade mTLS/DNS até a liberação do IP junto ao Serpro.
        """
        # Garante a existência do registro de controle no banco
        ControleNSU.objects.get_or_create(
            cliente=self.cliente,
            tipo_documento='NFSE',
            defaults={'ultimo_nsu': 0, 'max_nsu': 0},
        )

        base_url = _ADN_BASE_URL_HOMOLOG if self.homologacao else _ADN_BASE_URL_PROD
        logger.warning(
            f"NFS-e ADN: Barramento restingido pela NT 008/2026. "
            f"Aguardando liberação de IP dedicado para o endpoint {base_url}/nfse/"
        )
        
        # Retorna ERRO_CONEXAO para falhar silenciosamente no log,
        # permitindo que o Celery prossiga livremente com a NF-e e o CT-e.
        return 'ERRO_CONEXAO'

    def capturar_por_chave_direta(self, chave_acesso: str) -> str:
        """
        Executa a busca cirúrgica de uma nota pela Chave de Acesso (Item 1.3.2 do Manual).
        Pode ser invocado diretamente por uma rota do Frontend.
        """
        base_url = _ADN_BASE_URL_HOMOLOG if self.homologacao else _ADN_BASE_URL_PROD
        url = f'{base_url}/nfse/{chave_acesso}'

        try:
            resposta = self.con.enviar_requisicao_rest_mtls(url)
        except Exception as e:
            logger.error(f"Falha mTLS/DNS ao conectar na API ADN NFS-e: {e}")
            return 'ERRO_CONEXAO'

        if resposta.status_code == 404:
            return 'NOTA_NAO_ENCONTRADA'
        if resposta.status_code != 200:
            return 'ERRO_HTTP'

        try:
            payload = json.loads(resposta.text)
            xml_b64 = payload.get('xmlNfse') or payload.get('nfse', '')
        except json.JSONDecodeError:
            xml_b64 = resposta.text

        xml_puro = self._descompactar(xml_b64) if xml_b64 and not xml_b64.startswith('<') else xml_b64
        if not xml_puro:
            return 'XML_INVALIDO'

        emitente = 'EMITENTE NFS-e'
        valor = 0.0

        try:
            root = ET.fromstring(xml_puro)
            ns = (root.tag.split('}')[0] + '}') if '{' in root.tag else ''
            emit = root.find(f'.//{ns}prest/XNome') or root.find(f'.//{ns}Prestador/{ns}RazaoSocial')
            if emit is not None:
                emitente = emit.text
            val = root.find(f'.//{ns}valores/vServicos') or root.find(f'.//{ns}ValorServicos')
            if val is not None:
                valor = float(val.text)
        except ET.ParseError:
            pass

        self._persistir(xml_puro, chave_acesso, emitente, valor)
        return 'SUCESSO'