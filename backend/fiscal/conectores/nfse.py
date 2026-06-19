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
_MAX_LOTES_BUSCA_DIR  = 10


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

        lote_dfe = payload.get('LoteDFe', [])
        # ultNSU/maxNSU ausentes na resposta de fila vazia -- fallback para valor atual
        ult_nsu  = int(payload.get('ultNSU', controle.ultimo_nsu))
        max_nsu  = int(payload.get('maxNSU', controle.max_nsu))

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

        # Lote < 50 itens tambem indica fim da fila disponivel
        fila_esgotada = ult_nsu >= max_nsu or len(lote_dfe) < 50
        return 'FINALIZADO' if fila_esgotada else 'TEM_MAIS_DADOS'

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
        """Persiste um item de LoteDFe. Idempotente via get_or_create por chDFe."""
        chave      = item.get('chDFe', '')
        xml_puro   = item.get('xml', '')
        nsu_doc    = int(item.get('nsu', 0))
        tipo_papel = item.get('tipoPapel', '')

        if not chave or len(chave) != 44:
            logger.warning(
                'NFS-e NSU %s [%s]: chDFe invalida "%s" -- campos do item: %s -- ignorado.',
                nsu_doc, self.cliente.cnpj, chave[:20], list(item.keys()),
            )
            return

        if not xml_puro:
            logger.warning(
                'NFS-e NSU %s [%s]: campo xml vazio -- ignorado.',
                nsu_doc, self.cliente.cnpj,
            )
            return

        emitente, valor, data_emissao, competencia = self._extrair_campos_xml(xml_puro, nsu_doc)

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
                    'status':         'COMPLETO',
                    'papel_nfse':     tipo_papel,
                    'metadados': {
                        'nsu':        nsu_doc,
                        'papel_nfse': tipo_papel,
                    },
                },
            )
            if criado:
                Xml.objects.create(documento=documento, conteudo=xml_puro)
            elif not Xml.objects.filter(documento=documento).exists():
                Xml.objects.create(documento=documento, conteudo=xml_puro)

        except Exception as e:
            logger.error('Erro ao persistir NFS-e chave %s NSU %s: %s', chave[:10], nsu_doc, e)

    # -- parser flexivel de XML ------------------------------------------------

    def _extrair_campos_xml(
        self, xml_puro: str, nsu_doc: int
    ) -> tuple[str, float, date, str]:
        """
        Extrai (emitente, valor, data_emissao, competencia) do XML da NFS-e Nacional.

        Usa _deep_find() -- busca profunda insensivel a namespace e case --
        para resistir a mudancas silenciosas de tag pelo governo.
        Retorna defaults seguros se o XML estiver malformado.
        """
        emitente     = 'EMITENTE NFS-e'
        valor        = 0.0
        data_emissao = timezone.now().date()
        competencia  = timezone.now().strftime('%Y-%m')

        try:
            xml_bytes = xml_puro.encode('utf-8') if isinstance(xml_puro, str) else xml_puro
            root = ET.fromstring(xml_bytes)

            # Nome do prestador -- multiplos candidatos para cobrir variacoes de schema
            el = _deep_find(root, 'xNome', 'razaoSocial', 'nomeRazaoSocial', 'nome')
            if el is not None and el.text:
                emitente = el.text.strip()

            # Valor do servico
            el = _deep_find(root, 'vServicos', 'valorServicos', 'vServ', 'valorTotalServicos')
            if el is not None and el.text:
                try:
                    valor = float(el.text.replace(',', '.'))
                except ValueError:
                    pass

            # Data de emissao
            el = _deep_find(root, 'dhEmi', 'dtEmissaoNFs', 'dataEmissao', 'dhEmissao', 'dtEmissao')
            if el is not None and el.text:
                try:
                    data_emissao = date.fromisoformat(el.text[:10])
                    competencia  = data_emissao.strftime('%Y-%m')
                except ValueError:
                    pass

        except ET.ParseError:
            logger.warning('NFS-e NSU %s: XML invalido, campos extraidos com defaults.', nsu_doc)

        return emitente, valor, data_emissao, competencia
