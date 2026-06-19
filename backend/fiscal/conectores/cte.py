"""
Serviço de captura CT-e — CTeDistribuicaoDFe (SOAP).

Mesma mecânica do NF-e: NSU incremental, docZip (GZip+Base64), cStat 137/138.
Reutiliza a infra do NFeCapturaService com tipo_documento='CTE'.
"""
import logging
import xml.etree.ElementTree as ET
import base64
import gzip

from django.utils import timezone

from fiscal.models import ControleNSU, Documento, Xml

logger = logging.getLogger(__name__)


class CTeCapturaService:
    def __init__(self, conector_sefaz, cliente):
        self.con = conector_sefaz
        self.cliente = cliente

    def _descompactar_doc_zip(self, conteudo_base64: str):
        if not conteudo_base64:
            return None
        conteudo_base64 = conteudo_base64.strip()
        if conteudo_base64.startswith('<'):
            return conteudo_base64
        try:
            padding = len(conteudo_base64) % 4
            if padding:
                conteudo_base64 += '=' * (4 - padding)
            return gzip.decompress(base64.b64decode(conteudo_base64)).decode('utf-8')
        except Exception as e:
            logger.error(f"Erro ao descompactar CT-e docZip: {e}")
            return None

    def capturar_proximo_lote(self) -> str:
        from django.db import transaction
        with transaction.atomic():
            controle, _ = ControleNSU.objects.select_for_update().get_or_create(
                cliente=self.cliente,
                tipo_documento='CTE',
                defaults={'ultimo_nsu': 0, 'max_nsu': 0},
            )

        if controle.ultimo_nsu > 0 and controle.ultimo_nsu == controle.max_nsu:
            return 'UP_TO_DATE'

        try:
            resposta = self.con.consulta_ctes_cnpj(
                cnpj=self.cliente.cnpj,
                nsu=int(controle.ultimo_nsu),
            )
        except NotImplementedError:
            return 'NAO_IMPLEMENTADO'
        except Exception as e:
            logger.error(f"Falha na comunicação SEFAZ CT-e: {e}")
            return 'ERRO_CONEXAO'

        if resposta.status_code != 200:
            return 'ERRO_HTTP'

        try:
            # CORREÇÃO: Converte para bytes antes do parse para aceitar acentos da SEFAZ
            xml_bytes = resposta.text.encode('utf-8') if isinstance(resposta.text, str) else resposta.text
            root = ET.fromstring(xml_bytes)
            ns = (root.tag.split('}')[0] + '}') if root.tag.startswith('{') else ''

            cstat_elem = root.find(f'.//{ns}cStat')
            if cstat_elem is None:
                return 'XML_INVALIDO'

            cstat = cstat_elem.text

            if cstat == '137':
                controle.atualizado_em = timezone.now()
                controle.save()
                return 'VAZIO_AGUARDAR_1H'

            if cstat == '138':
                ult_nsu = root.find(f'.//{ns}ultNSU').text
                max_nsu = root.find(f'.//{ns}maxNSU').text
                docs_zip = root.findall(f'.//{ns}docZip')

                for doc_node in docs_zip:
                    xml_puro = self._descompactar_doc_zip(doc_node.text)
                    if not xml_puro:
                        continue

                    nsu_doc = doc_node.attrib.get('NSU', '0')
                    chave = f'35260612345678000195570010000000010000000{nsu_doc}'[-44:]
                    emitente = 'EMITENTE CT-e'
                    valor = 0.0

                    try:
                        # CORREÇÃO FASE 1: Conversão defensiva para bytes UTF-8 antes do processamento do XML
                        xml_puro_bytes = xml_puro.encode('utf-8') if isinstance(xml_puro, str) else xml_puro
                        cte_root = ET.fromstring(xml_puro_bytes)
                        
                        ns_i = (cte_root.tag.split('}')[0] + '}') if '{' in cte_root.tag else ''

                        ch = cte_root.find(f'.//{ns_i}chCTe')
                        if ch is not None:
                            chave = ch.text

                        emit = cte_root.find(f'.//{ns_i}xNome')
                        if emit is not None:
                            emitente = emit.text

                        val = cte_root.find(f'.//{ns_i}vTPrest')
                        if val is not None:
                            valor = float(val.text)

                    except ET.ParseError:
                        logger.warning(f"Erro de parser/encoding no CT-e do NSU {nsu_doc}.")
                        continue

                    try:
                        documento, criado = Documento.objects.get_or_create(
                            chave=chave,
                            defaults={
                                'cliente': self.cliente,
                                'tipo_documento': 'CTE',
                                'emitente': emitente,
                                'valor': valor,
                                'data_emissao': timezone.now().date(),
                                'competencia': timezone.now().strftime('%Y-%m'),
                                'status': 'CAPTURADO',
                            },
                        )
                        if criado:
                            Xml.objects.create(documento=documento, conteudo=xml_puro)
                        else:
                            try:
                                documento.xml
                            except Documento.xml.RelatedObjectDoesNotExist:
                                Xml.objects.create(documento=documento, conteudo=xml_puro)
                    except Exception as e:
                        logger.error(f"Erro ao persistir CT-e: {e}")
                        continue

                controle.ultimo_nsu = int(ult_nsu)
                controle.max_nsu = int(max_nsu)
                controle.atualizado_em = timezone.now()
                controle.save()

                return 'TEM_MAIS_DADOS' if controle.ultimo_nsu < controle.max_nsu else 'FINALIZADO'

            return 'REJEITADO'

        except ET.ParseError:
            logger.error('XML do lote CT-e corrompido.')
            return 'XML_CORROMPIDO'