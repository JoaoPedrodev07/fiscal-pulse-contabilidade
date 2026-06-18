"""
Serviço de Manifestação do Destinatário (NF-e).

Fluxo obrigatório pelo escopo:
  resNFe (resumo) → Ciência da Operação (210210) → procNFe (XML completo)

Sem a manifestação a SEFAZ não libera o XML completo da NF-e.
Prazo máximo: 90 dias da data de emissão — após isso o evento é rejeitado.
"""
import base64
import gzip
import logging
import xml.etree.ElementTree as ET

from fiscal.models import Documento, Manifestacao, StatusDocumento, Xml

logger = logging.getLogger(__name__)

_NS_NFE = 'http://www.portalfiscal.inf.br/nfe'


def _descompactar(conteudo_base64: str) -> str | None:
    conteudo_base64 = conteudo_base64.strip()
    if conteudo_base64.startswith('<'):
        return conteudo_base64
    try:
        padding = len(conteudo_base64) % 4
        if padding:
            conteudo_base64 += '=' * (4 - padding)
        return gzip.decompress(base64.b64decode(conteudo_base64)).decode('utf-8')
    except Exception:
        return None


def _buscar_e_salvar_xml_completo(conector, documento: Documento) -> bool:
    """
    Após cStat=135 (manifestação aceita), refaz a consulta com ultNSU = nsu-1
    para que a SEFAZ entregue o procNFe completo no lugar do resNFe (resumo).
    Salva o XML em Xml e atualiza documento.status = COMPLETO.
    Retorna True se o XML completo foi salvo com sucesso.
    """
    nsu = documento.metadados.get('nsu') if documento.metadados else None
    if not nsu:
        logger.warning(
            f"Documento {documento.chave[:10]}… sem NSU em metadados — "
            "XML completo não pode ser buscado."
        )
        return False

    try:
        resposta = conector.consulta_notas_cnpj(
            cnpj=documento.cliente.cnpj,
            nsu=int(nsu) - 1,
        )
        if resposta.status_code != 200:
            return False

        xml_bytes = resposta.text.encode('utf-8') if isinstance(resposta.text, str) else resposta.text
        root = ET.fromstring(xml_bytes)
        ns = (root.tag.split('}')[0] + '}') if root.tag.startswith('{') else ''

        cstat = root.find(f'.//{ns}cStat')
        if cstat is None or cstat.text != '138':
            return False

        for doc_node in root.findall(f'.//{ns}docZip'):
            xml_puro = _descompactar(doc_node.text or '')
            if not xml_puro:
                continue

            try:
                inner_bytes = xml_puro.encode('utf-8') if isinstance(xml_puro, str) else xml_puro
                inner_root = ET.fromstring(inner_bytes)
                ns_i = (inner_root.tag.split('}')[0] + '}') if '{' in inner_root.tag else ''

                ch = inner_root.find(f'.//{ns_i}chNFe')
                if ch is None or ch.text != documento.chave:
                    continue

                # procNFe encontrado — salva ou substitui XML
                try:
                    documento.xml.conteudo = xml_puro
                    documento.xml.save(update_fields=['conteudo'])
                except Xml.DoesNotExist:
                    Xml.objects.create(documento=documento, conteudo=xml_puro)

                documento.status = StatusDocumento.COMPLETO
                documento.save(update_fields=['status'])
                logger.info(f"XML completo salvo para {documento.chave[:10]}… — status=COMPLETO")
                return True

            except ET.ParseError:
                continue

    except Exception as e:
        logger.error(
            f"Erro ao buscar XML completo pós-manifestação para "
            f"{documento.chave[:10]}…: {e}"
        )

    return False


def _extrair_protocolo(xml_resposta: str) -> str:
    """Extrai nProt (número de protocolo) da resposta da SEFAZ."""
    try:
        root = ET.fromstring(xml_resposta)
        ns = f'{{{root.tag.split("}")[0][1:]}}}' if root.tag.startswith('{') else ''
        elem = root.find(f'.//{ns}nProt')
        return elem.text if elem is not None else ''
    except Exception:
        return ''


def _extrair_cstat(xml_resposta: str) -> str:
    try:
        root = ET.fromstring(xml_resposta)
        ns = f'{{{root.tag.split("}")[0][1:]}}}' if root.tag.startswith('{') else ''
        elem = root.find(f'.//{ns}cStat')
        return elem.text if elem is not None else ''
    except Exception:
        return ''


def manifestar_documento(conector, documento: Documento, tipo_evento: str = '210210') -> Manifestacao:
    """
    Envia o evento de manifestação e persiste o resultado em Manifestacao.

    Args:
        conector: ConectorSefaz da fábrica (já inicializado com o A1 do cliente).
        documento: instância de Documento com status CAPTURADO.
        tipo_evento: '210210' = Ciência da Operação (padrão e automático).

    Returns:
        Instância de Manifestacao persistida.
    """
    if hasattr(documento, 'manifestacao'):
        logger.info(f"Documento {documento.chave[:10]}… já manifestado. Pulando.")
        return documento.manifestacao

    sucesso = False
    protocolo = ''
    mensagem = ''

    try:
        resposta = conector.enviar_manifestacao(
            cnpj=documento.cliente.cnpj,
            chave_nfe=documento.chave,
            tipo_evento=tipo_evento,
        )

        cstat = _extrair_cstat(resposta.text)
        protocolo = _extrair_protocolo(resposta.text)

        # cStat 135 = Evento registrado e vinculado à NF-e
        if cstat in ('135', '573'):  # 573 = evento duplicado (já manifestado)
            sucesso = True
            documento.status = StatusDocumento.MANIFESTADO
            documento.save(update_fields=['status'])
            mensagem = f'cStat {cstat} — protocolo {protocolo}'
            logger.info(f"Manifestação aceita para {documento.chave[:10]}… — {mensagem}")
            # Busca imediata do procNFe completo após a SEFAZ aceitar a manifestação
            _buscar_e_salvar_xml_completo(conector, documento)
        else:
            mensagem = f'cStat {cstat} — {resposta.text[:200]}'
            logger.warning(f"Manifestação rejeitada para {documento.chave[:10]}…: {mensagem}")

    except Exception as e:
        mensagem = str(e)
        logger.error(f"Erro ao manifestar {documento.chave[:10]}…: {mensagem}")

    return Manifestacao.objects.create(
        documento=documento,
        tipo_evento=tipo_evento,
        protocolo=protocolo,
        sucesso=sucesso,
        mensagem=mensagem,
    )
