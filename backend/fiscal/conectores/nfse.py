"""
Serviço de captura NFS-e Nacional — API ADN (REST + mTLS).

Endpoint base: https://adnapi.nfse.gov.br
Métodos relevantes:
  GET /DFe/{NSU}       — busca documento por NSU
  GET /NFSe/{chave}    — busca por chave

Resposta: JSON com campo 'xmlNfse' em GZip+Base64 ou campo 'nfse' com XML.
Cobertura atual: Rio de Janeiro + Niterói (padrão nacional desde 01/jan/2026).

ATENÇÃO: O ADN usa ambiente de PRODUÇÃO RESTRITA para testes —
não há sandbox separado. Use sempre CNPJ e certificado de homologação válidos.
"""
import base64
import gzip
import json
import logging
import xml.etree.ElementTree as ET

from django.utils import timezone

from fiscal.models import ControleNSU, Documento, Xml

logger = logging.getLogger(__name__)

_ADN_BASE_URL = 'https://api.nfse.gov.br/v1/adn'


class NFSeADNCapturaService:
    """
    Captura NFS-e via API REST do ADN Nacional.

    O conector_sefaz aqui é usado apenas para obter a sessão mTLS —
    não é a mesma instância usada para NF-e/CT-e SOAP.
    Para NFS-e o ConectorSefaz ainda não expõe método REST nativo;
    este serviço monta a sessão requests diretamente via ConectorSefaz._run
    adaptado para REST (implementar quando PyNFe expor REST ADN).

    Status atual: estrutura pronta, validar API ADN em homologação.
    """

    def __init__(self, conector_sefaz, cliente):
        self.con = conector_sefaz
        self.cliente = cliente

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
                    'status': 'COMPLETO',  # NFS-e não tem fluxo de manifestação
                },
            )
            if criado or not hasattr(documento, 'xml'):
                Xml.objects.get_or_create(documento=documento, defaults={'conteudo': xml_puro})
        except Exception as e:
            logger.error(f"Erro ao persistir NFS-e chave {chave[:10]}…: {e}")

    def capturar_proximo_lote(self) -> str:
        """
        Consulta o próximo NSU de NFS-e no ADN.
        Retorna os mesmos códigos de status do NFeCapturaService para
        compatibilidade com o loop em tasks.py.
        """
        controle, _ = ControleNSU.objects.get_or_create(
            cliente=self.cliente,
            tipo_documento='NFSE',
            defaults={'ultimo_nsu': 0, 'max_nsu': 0},
        )

        if controle.ultimo_nsu > 0 and controle.ultimo_nsu == controle.max_nsu:
            return 'UP_TO_DATE'

        proximo_nsu = controle.ultimo_nsu + 1
        url = f'{_ADN_BASE_URL}/dfe/nsus/{proximo_nsu}'

        try:
            resposta = self.con.consulta_nfse_nsu(nsu=proximo_nsu)
        except AttributeError:
            # ConectorSefaz ainda não tem consulta_nfse_nsu — implementar via requests + mTLS
            logger.warning('consulta_nfse_nsu não implementado no ConectorSefaz. Aguardando suporte REST ADN.')
            return 'ERRO_CONEXAO'
        except Exception as e:
            logger.error(f"Falha na comunicação ADN NFS-e: {e}")
            return 'ERRO_CONEXAO'

        if resposta.status_code == 404:
            return 'VAZIO_AGUARDAR_1H'

        if resposta.status_code != 200:
            return 'ERRO_HTTP'

        try:
            payload = json.loads(resposta.text)
        except json.JSONDecodeError:
            # Alguns endpoints retornam XML diretamente
            payload = {'xmlNfse': resposta.text}

        xml_b64 = payload.get('xmlNfse') or payload.get('nfse', '')
        xml_puro = self._descompactar(xml_b64) if xml_b64 and not xml_b64.startswith('<') else xml_b64

        if not xml_puro:
            return 'XML_INVALIDO'

        chave = str(proximo_nsu).zfill(44)
        emitente = 'EMITENTE NFS-e'
        valor = 0.0

        try:
            root = ET.fromstring(xml_puro)
            ns = (root.tag.split('}')[0] + '}') if '{' in root.tag else ''
            
            # Padrão Nacional ADN/DPS busca chNFSe ou o Id da tag principal
            ch = root.find(f'.//{ns}chNFSe') or root.find(f'.//{ns}chDFe')
            if ch is not None:
                chave = ch.text
            else:
                # Fallback para o atributo Id se a chave direta não estiver acessível
                id_attr = root.attrib.get('Id') or (root.find(f'.//{ns}infNFSe').attrib.get('Id') if root.find(f'.//{ns}infNFSe') is not None else None)
                if id_attr:
                    chave = ''.join(c for c in id_attr if c.isdigit()).zfill(44)[-44:]

            # Prestador do Serviço (Emitente)
            emit = root.find(f'.//{ns}prest/XNome') or root.find(f'.//{ns}Prestador/{ns}RazaoSocial') or root.find(f'.//{ns}xNome')
            if emit is not None:
                emitente = emit.text
                
            # Valor do Serviço (vServicos ou vNF)
            val = root.find(f'.//{ns}valores/vServicos') or root.find(f'.//{ns}ValorServicos') or root.find(f'.//{ns}vNF')
            if val is not None:
                valor = float(val.text)
                
        except ET.ParseError:
            logger.warning(f"NFS-e NSU {proximo_nsu} — XML não parseável, persiste como recebido.")

        self._persistir(xml_puro, chave, emitente, valor)

        controle.ultimo_nsu = proximo_nsu
        controle.atualizado_em = timezone.now()
        controle.save()

        return 'TEM_MAIS_DADOS'
