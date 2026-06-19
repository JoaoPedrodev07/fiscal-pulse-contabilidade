"""
Conector NFS-e Nacional -- API ADN/Serpro (REST + mTLS).

Endpoint:
  Homologacao: https://adn.producaorestrita.nfse.gov.br/contribuintes/DFe/{ultimoNSU}
  Producao:    https://adn.nfse.gov.br/contribuintes/DFe/{ultimoNSU}

Query param opcional: ?cnpjConsulta=CNPJ
  Sem o param: ADN usa o CNPJ exato do certificado A1.
  Com o param: permite consultar filial que compartilha o CNPJ raiz (8 digitos).

Campos reais auditados (homologacao 2026-06-18):
  Payload fila vazia (HTTP 404):
    {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO",
     "LoteDFe": [], "Erros": [...], "TipoAmbiente": "HOMOLOGACAO"}
  Payload com documentos (HTTP 200, estrutura per NT 008/2026):
    {"LoteDFe": [{"nsu":N,"chDFe":"<44 digs>","xml":"...","tipoPapel":"TOMADOR|EMITENTE"}],
     "ultNSU": N, "maxNSU": N, ...}

Notas de protocolo:
  - HTTP 404 com JSON = fila vazia (valido, nao e erro).
  - HTTP 200 com LoteDFe nao vazio = documentos disponíveis.
  - ultNSU/maxNSU ausentes na resposta de fila vazia.
  - tipoPapel gravado em Documento.papel_nfse (campo de 1a classe) e metadados['papel_nfse'].
"""
import base64
import gzip
import json
import logging
import os
import xml.etree.ElementTree as ET
from datetime import date

from django.db import transaction
from django.utils import timezone

from fiscal.models import ControleNSU, Documento, Xml

logger = logging.getLogger(__name__)

_ADN_BASE_HOMOLOG = 'https://adn.producaorestrita.nfse.gov.br/contribuintes'
_ADN_BASE_PROD    = 'https://adn.nfse.gov.br/contribuintes'

_VALID_HTTP_CODES     = {200, 404}
_MAX_LOTES_BUSCA_DIR  = 20

# cStat da NFS-e Nacional que indicam cancelamento ou substituição
_CSTAT_CANCELADO   = {101, 107, 108, 109, 110, 111, 112, 132, 133, 134, 135, 155, 301, 302}
_CSTAT_SUBSTITUIDO = {150, 151, 152, 153, 154}
_TAGS_CANCELAMENTO = {'infcanc', 'cancnfse', 'nfsecancelada', 'eventocancelamento', 'infcancelamento'}
_TAGS_SUBSTITUICAO = {'nfsesubst', 'chnfsesubst', 'nfsesubstituta', 'infsubstituicao'}


# -- Parser flexivel de XML ----------------------------------------------------

def _deep_find(root: ET.Element, *tag_candidates: str) -> ET.Element | None:
    """
    Busca profunda e insensivel a maiusculas/minusculas e namespace.

    Itera toda a arvore XML comparando apenas o nome local (sem namespace)
    com qualquer um dos candidatos fornecidos -- insensivel a case.

    Exemplo:
        _deep_find(root, 'chNFSe', 'chNFe', 'chave')
    funciona mesmo que o governo mude 'chNFSe' para 'ChNfse' sem aviso.
    """
    lower = {c.lower() for c in tag_candidates}
    for el in root.iter():
        local = el.tag.split('}')[-1].lower()
        if local in lower:
            return el
    return None


def _cnpj_em_secao(root: ET.Element, *secao_candidatos: str) -> str:
    """Retorna o CNPJ (14 dígitos) dentro da primeira seção correspondente a um candidato."""
    secoes = {c.lower() for c in secao_candidatos}
    for el in root.iter():
        if el.tag.split('}')[-1].lower() in secoes:
            for child in el.iter():
                if child.tag.split('}')[-1].lower() == 'cnpj' and child.text:
                    digits = ''.join(c for c in child.text if c.isdigit())
                    if len(digits) == 14:
                        return digits
    return ''


def _determinar_papel_nfse(root: ET.Element | None, cliente_cnpj: str) -> str:
    """
    Determina EMITENTE ou TOMADOR comparando o CNPJ do prestador da nota
    com o CNPJ do cliente que fez a consulta ao ADN.

    A NFS-e Nacional (NT 008/2026) usa <emit> na raiz e <prest> dentro do DPS.
    Se o CNPJ do prestador bate com o cliente → EMITENTE (emitiu a nota).
    Caso contrário → TOMADOR (recebeu/tomou o serviço).
    Retorna '' se o XML não tiver CNPJ identificável de prestador.
    """
    if root is None:
        return ''
    prestador_cnpj = _cnpj_em_secao(
        root, 'emit', 'prest', 'emitente', 'prestador', 'dadosprestador', 'infprestador',
    )
    if not prestador_cnpj:
        return ''
    return 'EMITENTE' if prestador_cnpj == cliente_cnpj else 'TOMADOR'


def _extrair_status_nfse(root: ET.Element | None) -> str:
    """
    Determina o status da NFS-e a partir do cStat ou de tags estruturais de cancelamento.
    Retorna: 'COMPLETO' | 'CANCELADO' | 'SUBSTITUIDO'
    """
    if root is None:
        return 'COMPLETO'

    el = _deep_find(root, 'cStat', 'cSitNFSe', 'situacaoNFSe')
    if el is not None and el.text:
        try:
            cstat = int(el.text.strip())
            if cstat in _CSTAT_CANCELADO:
                return 'CANCELADO'
            if cstat in _CSTAT_SUBSTITUIDO:
                return 'SUBSTITUIDO'
        except ValueError:
            pass

    # Detecta cancelamento/substituição por tags estruturais (fallback)
    for el in root.iter():
        local = el.tag.split('}')[-1].lower()
        if local in _TAGS_SUBSTITUICAO:
            return 'SUBSTITUIDO'
        if local in _TAGS_CANCELAMENTO:
            return 'CANCELADO'

    return 'COMPLETO'


# -- Servico -------------------------------------------------------------------

class NFSeADNCapturaService:

    def __init__(self, conector_sefaz, cliente):
        self.con = conector_sefaz
        self.cliente = cliente
        self._homologacao = os.environ.get('SEFAZ_HOMOLOGACAO', 'True') != 'False'

    @property
    def _base_url(self) -> str:
        return _ADN_BASE_HOMOLOG if self._homologacao else _ADN_BASE_PROD

    # -- chamada REST ----------------------------------------------------------

    def _chamar_adn(self, ultimo_nsu: int):
        """GET /DFe/{ultimoNSU}?cnpjConsulta={cnpj} via mTLS."""
        url = f'{self._base_url}/DFe/{ultimo_nsu}?cnpjConsulta={self.cliente.cnpj}'
        return self.con.enviar_requisicao_rest_mtls(url)

    def _parse_resposta(self, resposta) -> dict | None:
        if resposta.status_code not in _VALID_HTTP_CODES:
            logger.error(
                'ADN NFS-e HTTP %s [%s]: %s',
                resposta.status_code, self.cliente.cnpj, resposta.text[:200],
            )
            return None
        try:
            return json.loads(resposta.text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error('Resposta ADN nao e JSON [%s]: %s', self.cliente.cnpj, e)
            return None

    # -- loop principal --------------------------------------------------------

    def capturar_proximo_lote(self) -> str:
        """
        Busca o proximo lote de NFS-e a partir do ultimo NSU controlado.

        Retorna o mesmo vocabulario de status que NFeCapturaService:
          UP_TO_DATE        -- ja processamos ate maxNSU
          VAZIO_AGUARDAR_1H -- ADN confirmou fila vazia
          TEM_MAIS_DADOS    -- lote processado, mais disponíveis (ultNSU < maxNSU)
          FINALIZADO        -- lote processado, fila esgotada (ultNSU >= maxNSU)
          ERRO_CONEXAO      -- falha de rede ou mTLS
          ERRO_HTTP         -- ADN retornou status inesperado
          XML_INVALIDO      -- resposta nao e JSON valido
        """
        with transaction.atomic():
            controle, _ = ControleNSU.objects.select_for_update().get_or_create(
                cliente=self.cliente,
                tipo_documento='NFSE',
                defaults={'ultimo_nsu': 0, 'max_nsu': 0},
            )

        if controle.ultimo_nsu > 0 and controle.ultimo_nsu >= controle.max_nsu:
            return 'UP_TO_DATE'

        try:
            resposta = self._chamar_adn(controle.ultimo_nsu)
        except Exception as e:
            logger.error('Falha mTLS/conexao ADN NFS-e [%s]: %s', self.cliente.cnpj, e)
            return 'ERRO_CONEXAO'

        if resposta.status_code not in _VALID_HTTP_CODES:
            logger.error(
                'ADN NFS-e HTTP %s [%s]: %s',
                resposta.status_code, self.cliente.cnpj, resposta.text[:200],
            )
            return 'ERRO_HTTP'

        payload = self._parse_resposta(resposta)
        if payload is None:
            return 'XML_INVALIDO'

        lote_dfe = payload.get('LoteDFe', payload.get('loteDFe', []))

        # Log dos campos raiz para diagnostico de campo NSU em producao
        logger.info(
            'ADN NFS-e [%s] payload keys=%s lote=%d',
            self.cliente.cnpj, list(payload.keys()), len(lote_dfe),
        )

        # ultNSU/maxNSU: tenta PascalCase e camelCase
        ult_nsu = int(payload.get('UltNSU', payload.get('ultNSU', 0)))
        max_nsu = int(payload.get('MaxNSU', payload.get('maxNSU', 0)))

        # Fallback: se o ADN nao retornou os campos de controle NSU,
        # deriva ult_nsu do maior NSU presente nos proprios itens do lote.
        # max_nsu = ult_nsu + 1 forca TEM_MAIS_DADOS ate o ADN devolver lote vazio.
        if ult_nsu == 0 and lote_dfe:
            ult_nsu = max(
                int(item.get('NSU', item.get('nsu', 0)))
                for item in lote_dfe
            )
        if max_nsu == 0 and ult_nsu > 0:
            max_nsu = ult_nsu + 1

        if not lote_dfe:
            # Fila vazia: nao avanca o ponteiro de NSU (ADN nao retorna ultNSU neste caso)
            controle.atualizado_em = timezone.now()
            controle.save(update_fields=['atualizado_em'])
            logger.info(
                'ADN NFS-e fila vazia [%s] status=%s',
                self.cliente.cnpj, payload.get('StatusProcessamento', '?'),
            )
            return 'VAZIO_AGUARDAR_1H'

        for item in lote_dfe:
            self._persistir_item(item)

        controle.ultimo_nsu    = ult_nsu
        controle.max_nsu       = max_nsu
        controle.atualizado_em = timezone.now()
        controle.save()

        # Para apenas quando NSU atual atingiu o maximo confirmado pelo ADN
        return 'FINALIZADO' if ult_nsu >= max_nsu else 'TEM_MAIS_DADOS'

    # -- busca direta por chave (fallback React) --------------------------------

    def capturar_por_chave_direta(self, chave: str) -> str:
        """
        Verifica se a NFS-e ja esta no banco.
        Se nao estiver, dispara captura incremental ate _MAX_LOTES_BUSCA_DIR lotes.

        Retorna: SUCESSO | NOTA_NAO_ENCONTRADA | ERRO_CONEXAO | ERRO_HTTP | XML_INVALIDO
        """
        if Documento.objects.filter(chave=chave).exists():
            return 'SUCESSO'

        for _ in range(_MAX_LOTES_BUSCA_DIR):
            resultado = self.capturar_proximo_lote()
            if resultado in ('ERRO_CONEXAO', 'ERRO_HTTP', 'XML_INVALIDO'):
                return resultado
            if resultado in ('VAZIO_AGUARDAR_1H', 'UP_TO_DATE', 'FINALIZADO'):
                break

        return 'SUCESSO' if Documento.objects.filter(chave=chave).exists() else 'NOTA_NAO_ENCONTRADA'

    # -- persistencia ----------------------------------------------------------

    def _persistir_item(self, item: dict) -> None:
        """Persiste um item de LoteDFe. Idempotente via get_or_create por ChaveAcesso."""
        chave    = item.get('ChaveAcesso', item.get('chDFe', ''))
        xml_puro = item.get('ArquivoXml',  item.get('xml', ''))
        nsu_doc  = int(item.get('NSU', item.get('nsu', 0)))

        if not chave or len(chave) not in (44, 50):
            logger.warning(
                'NFS-e NSU %s [%s]: chave invalida len=%s valor="%s" -- ignorado.',
                nsu_doc, self.cliente.cnpj, len(chave), chave,
            )
            return

        if not xml_puro:
            logger.warning(
                'NFS-e NSU %s [%s]: campo xml vazio -- ignorado.',
                nsu_doc, self.cliente.cnpj,
            )
            return

        xml_puro = self._decodificar_xml(xml_puro, nsu_doc)
        if not xml_puro:
            return

        # Parse unico: root alimenta extracao de campos e de status
        root = None
        try:
            xml_bytes = xml_puro.encode('utf-8') if isinstance(xml_puro, str) else xml_puro
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            logger.warning('NFS-e NSU %s: XML invalido, campos extraidos com defaults.', nsu_doc)

        emitente, valor, data_emissao, competencia = self._extrair_campos_xml(root, nsu_doc)
        status = _extrair_status_nfse(root)
        papel  = _determinar_papel_nfse(root, self.cliente.cnpj)

        logger.debug('NFS-e NSU %s chave %s status=%s papel=%s', nsu_doc, chave[:10], status, papel)

        try:
            documento, criado = Documento.objects.get_or_create(
                chave=chave,
                defaults={
                    'cliente':        self.cliente,
                    'tipo_documento': 'NFSE',
                    'emitente':       emitente,
                    'valor':          valor,
                    'data_emissao':   data_emissao,
                    'competencia':    competencia,
                    'status':         status,
                    'papel_nfse':     papel,
                    'metadados': {
                        'nsu':        nsu_doc,
                        'papel_nfse': papel,
                    },
                },
            )
            if not criado:
                updates = {}
                if documento.status != status:
                    updates['status'] = status
                if papel and documento.papel_nfse != papel:
                    updates['papel_nfse'] = papel
                if updates:
                    for k, v in updates.items():
                        setattr(documento, k, v)
                    documento.save(update_fields=list(updates.keys()))
            if criado:
                Xml.objects.create(documento=documento, conteudo=xml_puro)
            elif not Xml.objects.filter(documento=documento).exists():
                Xml.objects.create(documento=documento, conteudo=xml_puro)

        except Exception as e:
            logger.error('Erro ao persistir NFS-e chave %s NSU %s: %s', chave[:10], nsu_doc, e)

    # -- decodificacao base64+gzip ---------------------------------------------

    def _decodificar_xml(self, conteudo: str, nsu_doc: int) -> str | None:
        """
        ADN producao retorna ArquivoXml como base64(gzip(xml)).
        Tenta decodificar; se ja for XML puro, retorna como esta.
        """
        try:
            raw = base64.b64decode(conteudo)
            return gzip.decompress(raw).decode('utf-8')
        except Exception:
            pass
        # Ja e XML puro (homologacao ou futuras versoes)
        if conteudo.lstrip().startswith('<'):
            return conteudo
        logger.warning('NFS-e NSU %s: nao foi possivel decodificar ArquivoXml.', nsu_doc)
        return None

    # -- parser flexivel de XML ------------------------------------------------

    def _extrair_campos_xml(
        self, root: ET.Element | None, nsu_doc: int
    ) -> tuple[str, float, date, str]:
        """
        Extrai (emitente, valor, data_emissao, competencia) de um root ja parseado.
        Retorna defaults seguros se root for None (XML invalido).
        """
        emitente     = 'EMITENTE NFS-e'
        valor        = 0.0
        data_emissao = timezone.now().date()
        competencia  = timezone.now().strftime('%Y-%m')

        if root is None:
            return emitente, valor, data_emissao, competencia

        el = _deep_find(root, 'xNome', 'razaoSocial', 'nomeRazaoSocial', 'nome')
        if el is not None and el.text:
            emitente = el.text.strip()

        el = _deep_find(root, 'vServicos', 'valorServicos', 'vServ', 'valorTotalServicos')
        if el is not None and el.text:
            try:
                valor = float(el.text.replace(',', '.'))
            except ValueError:
                pass

        el = _deep_find(root, 'dhEmi', 'dtEmissaoNFs', 'dataEmissao', 'dhEmissao', 'dtEmissao')
        if el is not None and el.text:
            try:
                data_emissao = date.fromisoformat(el.text[:10])
                competencia  = data_emissao.strftime('%Y-%m')
            except ValueError:
                pass

        return emitente, valor, data_emissao, competencia
