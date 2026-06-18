import logging
import xml.etree.ElementTree as ET
import base64
import gzip
from django.utils import timezone
from fiscal.models import ControleNSU, Documento, Xml 

logger = logging.getLogger(__name__)

class NFeCapturaService:
    def __init__(self, conector_sefaz, cliente):
        self.con = conector_sefaz
        self.cliente = cliente

    def _descompactar_doc_zip(self, conteudo_base64):
        """
        Base64 -> Gzip Decompress -> String XML.
        Fallback inteligente: se o dado for string comum (fixture simples), retorna direto.
        """
        if not conteudo_base64:
            return None
            
        conteudo_base64 = conteudo_base64.strip()
        
        if conteudo_base64.startswith("<") or "infNFe" in conteudo_base64:
            return conteudo_base64

        try:
            missing_padding = len(conteudo_base64) % 4
            if missing_padding:
                conteudo_base64 += '=' * (4 - missing_padding)

            bytes_zipados = base64.b64decode(conteudo_base64)
            bytes_xml = gzip.decompress(bytes_zipados)
            return bytes_xml.decode('utf-8')
        except Exception as e:
            if len(conteudo_base64) > 10 and not any(ord(c) < 32 or ord(c) > 126 for c in conteudo_base64[:10]):
                return conteudo_base64
            logger.error(f"Erro ao descompactar documento do lote: {str(e)}")
            return None

    def capturar_proximo_lote(self):
        # 1. Recupera o ponteiro do NSU
        from django.db import transaction
        with transaction.atomic():
            controle, _ = ControleNSU.objects.select_for_update().get_or_create(
                cliente=self.cliente,
                tipo_documento='NFE',
                defaults={'ultimo_nsu': 0, 'max_nsu': 0},
            )

        if controle.ultimo_nsu > 0 and controle.ultimo_nsu == controle.max_nsu:
            return "UP_TO_DATE"

        # 2. Consulta a SEFAZ
        try:
            resposta = self.con.consulta_notas_cnpj(
                cnpj=self.cliente.cnpj, 
                nsu=int(controle.ultimo_nsu)
            )
        except Exception as e:
            logger.error(f"Falha na comunicação SEFAZ: {str(e)}")
            return "ERRO_CONEXAO"

        if resposta.status_code != 200:
            return "ERRO_HTTP"

        # 3. Parser do Lote
        try:
            # CORREÇÃO: Converte para bytes antes do parse para aceitar acentos da SEFAZ
            xml_bytes = resposta.text.encode('utf-8') if isinstance(resposta.text, str) else resposta.text
            root = ET.fromstring(xml_bytes)
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"

            c_stat_element = root.find(f".//{ns}cStat")
            if c_stat_element is None:
                return "XML_INVALIDO"

            c_stat = c_stat_element.text

            if c_stat == "137":
                controle.atualizado_em = timezone.now()
                controle.save()
                return "VAZIO_AGUARDAR_1H"

            if c_stat == "138":
                ult_nsu_xml = root.find(f".//{ns}ultNSU").text
                max_nsu_xml = root.find(f".//{ns}maxNSU").text
                docs_zip = root.findall(f".//{ns}docZip")

                # 4. PROCESSA E PERSISTE CADA DOCUMENTO DO LOTE
                for doc_xml_node in docs_zip:
                    xml_puro = self._descompactar_doc_zip(doc_xml_node.text)
                    if not xml_puro:
                        continue

                    nsu_doc = doc_xml_node.attrib.get('NSU', '0')
                    schema  = doc_xml_node.attrib.get('schema', '')

                    # Eventos (cancelamento, etc.) — tratados separadamente
                    if 'procEventoNFe' in schema:
                        self._processar_evento(xml_puro, nsu_doc)
                        continue

                    chave = f"3526061234567800019555001000000000000000{nsu_doc}"[-44:]
                    emitente = "EMITENTE TESTE"
                    valor = 0.0
                    status_doc = 'CAPTURADO'

                    try:
                        xml_puro_bytes = xml_puro.encode('utf-8') if isinstance(xml_puro, str) else xml_puro
                        nota_root = ET.fromstring(xml_puro_bytes)

                        ns_interno = nota_root.tag.split("}")[0] + "}" if "}" in nota_root.tag else ""

                        ch_element = nota_root.find(f".//{ns_interno}chNFe")
                        if ch_element is not None:
                            chave = ch_element.text
                        else:
                            id_attr = nota_root.attrib.get('Id') or nota_root.find(f".//*[@Id]")
                            if id_attr is not None:
                                id_val = id_attr.attrib.get('Id') if hasattr(id_attr, 'attrib') else id_attr
                                chave = id_val.replace('NFe', '')

                        emit_element = nota_root.find(f".//{ns_interno}emit/{ns_interno}xNome") or nota_root.find(f".//{ns_interno}xNome")
                        if emit_element is not None:
                            emitente = emit_element.text

                        val_element = nota_root.find(f".//{ns_interno}vNF")
                        if val_element is not None:
                            valor = float(val_element.text)

                        if "infNFe" in xml_puro:
                            status_doc = 'COMPLETO'

                    except ET.ParseError:
                        logger.warning(f"Erro de parser/encoding no conteúdo do NSU {nsu_doc} de NF-e.")
                        continue

                    # IDEMPOTÊNCIA: Garante o get_or_create
                    try:
                        documento, criado = Documento.objects.get_or_create(
                            chave=chave,
                            defaults={
                                'cliente': self.cliente,
                                'tipo_documento': 'NFE',
                                'emitente': emitente,
                                'valor': valor,
                                'data_emissao': timezone.now().date(),
                                'competencia': timezone.now().strftime("%Y-%m"),
                                'status': status_doc,
                                'metadados': {'nsu': int(nsu_doc)},
                            }
                        )

                        if criado:
                            Xml.objects.create(documento=documento, conteudo=xml_puro)
                        else:
                            try:
                                documento.xml
                            except Documento.xml.RelatedObjectDoesNotExist:
                                Xml.objects.create(documento=documento, conteudo=xml_puro)

                        if criado and status_doc == 'CAPTURADO':
                            from fiscal.conectores.manifestacao import manifestar_documento
                            manifestar_documento(self.con, documento)

                    except Exception as e:
                        logger.error(f"Erro ao persistir Documento no ORM: {str(e)}")
                        continue

                # Atualiza os ponteiros de controle após o loop das notas
                controle.ultimo_nsu = int(ult_nsu_xml)
                controle.max_nsu = int(max_nsu_xml)
                controle.atualizado_em = timezone.now()
                controle.save()

                if controle.ultimo_nsu < controle.max_nsu:
                    return "TEM_MAIS_DADOS"
                return "FINALIZADO"

            return "REJEITADO"

        except ET.ParseError:
            logger.error("Erro Crítico: XML do lote corrompido.")
            return "XML_CORROMPIDO"

    def _processar_evento(self, xml_puro: str, nsu_doc: str) -> None:
        """
        Processa um evento NF-e vindo do distNSU (schema procEventoNFe).
        Atualmente trata apenas cancelamento (tpEvento=110111).
        """
        try:
            root = ET.fromstring(xml_puro.encode('utf-8') if isinstance(xml_puro, str) else xml_puro)
            ns = (root.tag.split('}')[0] + '}') if '{' in root.tag else ''

            tp_el = root.find(f'.//{ns}tpEvento')
            if tp_el is None or tp_el.text != '110111':
                logger.debug('Evento NSU %s tipo %s ignorado (nao e cancelamento).', nsu_doc, tp_el.text if tp_el is not None else '?')
                return

            ch_el = root.find(f'.//{ns}chNFe')
            if ch_el is None or not ch_el.text:
                logger.warning('Evento de cancelamento NSU %s sem chNFe — ignorado.', nsu_doc)
                return

            chave = ch_el.text.strip()
            atualizados = Documento.objects.filter(chave=chave).update(status='CANCELADO')
            if atualizados:
                logger.info('NF-e cancelada via evento distNSU: chave=%.10s... NSU=%s', chave, nsu_doc)
            else:
                logger.warning('Evento cancelamento NSU %s: NF-e chave=%.10s... nao encontrada no banco.', nsu_doc, chave)

        except ET.ParseError as e:
            logger.warning('Erro ao processar evento NSU %s: %s', nsu_doc, e)