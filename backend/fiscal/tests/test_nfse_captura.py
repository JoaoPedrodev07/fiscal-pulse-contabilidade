"""
Testes determinísticos do conector NFS-e ADN (REST + mTLS).

Cobre:
  1. _determinar_papel_nfse  — EMITENTE, TOMADOR, XML sem CNPJ, root=None
  2. _extrair_status_nfse    — COMPLETO, CANCELADO, SUBSTITUIDO por cStat e por tags
  3. NFSeADNCapturaService.capturar_proximo_lote — todos os estados do protocolo ADN
  4. Persistência e idempotência no banco

NUNCA chama o ADN real — toda rede é mockada via unittest.mock.
"""
import base64
import gzip
import json
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

from django.test import TestCase

from fiscal.conectores.nfse import (
    NFSeADNCapturaService,
    _determinar_papel_nfse,
    _extrair_status_nfse,
)
from fiscal.models import Cliente, ControleNSU, Documento, Xml


# ── Helpers de fixture ─────────────────────────────────────────────────────────

CNPJ_PRESTADOR = "12345678000199"
CNPJ_TOMADOR   = "98765432000110"
CHAVE_44       = "35260112345678000199550010000000010000000001"
CHAVE_50       = "35260112345678000199550010000000010000000001000001"


def _gz64(xml_text: str) -> str:
    return base64.b64encode(gzip.compress(xml_text.encode("utf-8"))).decode("ascii")


def _nfse_xml(prestador_cnpj: str = CNPJ_PRESTADOR,
              emitente: str = "Prestador LTDA",
              valor: str = "500.00",
              data: str = "2026-01-15",
              cstat: int | None = None) -> str:
    cstat_block = f"<cStat>{cstat}</cStat>" if cstat is not None else ""
    return (
        f'<CompNfse xmlns="http://www.sped.fazenda.gov.br/nfse">'
        f'<Nfse><InfNfse>'
        f'{cstat_block}'
        f'<emit><CNPJ>{prestador_cnpj}</CNPJ><xNome>{emitente}</xNome></emit>'
        f'<ValoresNfse><vServicos>{valor}</vServicos></ValoresNfse>'
        f'<dhEmi>{data}T10:00:00</dhEmi>'
        f'</InfNfse></Nfse>'
        f'</CompNfse>'
    )


def _payload_adn(chave: str = CHAVE_44,
                 xml_text: str = "",
                 ult_nsu: int = 1,
                 max_nsu: int = 1,
                 nsu: int = 1) -> dict:
    return {
        "LoteDFe": [{
            "NSU": nsu,
            "ChaveAcesso": chave,
            "ArquivoXml": _gz64(xml_text or _nfse_xml()),
        }],
        "UltNSU": ult_nsu,
        "MaxNSU": max_nsu,
    }


def _payload_vazio() -> dict:
    return {
        "StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO",
        "LoteDFe": [],
        "Erros": [],
        "TipoAmbiente": "HOMOLOGACAO",
    }


def _mock_http(payload: dict, status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = json.dumps(payload)
    return r


def _cliente() -> Cliente:
    return Cliente.objects.create(cnpj=CNPJ_PRESTADOR, razao_social="Prestador LTDA")


def _service(cliente: Cliente, resposta_mock=None) -> NFSeADNCapturaService:
    con = MagicMock()
    if resposta_mock is not None:
        con.enviar_requisicao_rest_mtls.return_value = resposta_mock
    return NFSeADNCapturaService(conector_sefaz=con, cliente=cliente)


# ══════════════════════════════════════════════════════════════════════════════
# 1. _determinar_papel_nfse — EMITENTE vs TOMADOR
# ══════════════════════════════════════════════════════════════════════════════

class TestDeterminarPapelNfse(TestCase):

    def _root(self, cnpj_prestador: str) -> ET.Element:
        return ET.fromstring(_nfse_xml(prestador_cnpj=cnpj_prestador))

    def test_emitente_quando_cnpj_prestador_bate_com_cliente(self):
        root = self._root(CNPJ_PRESTADOR)
        papel = _determinar_papel_nfse(root, CNPJ_PRESTADOR)
        self.assertEqual(papel, "EMITENTE")

    def test_tomador_quando_cnpj_prestador_diferente_do_cliente(self):
        root = self._root(CNPJ_PRESTADOR)
        papel = _determinar_papel_nfse(root, CNPJ_TOMADOR)
        self.assertEqual(papel, "TOMADOR")

    def test_retorna_vazio_quando_xml_nao_tem_cnpj_de_prestador(self):
        xml_sem_cnpj = "<CompNfse><Nfse><InfNfse><emit><xNome>X</xNome></emit></InfNfse></Nfse></CompNfse>"
        root = ET.fromstring(xml_sem_cnpj)
        papel = _determinar_papel_nfse(root, CNPJ_PRESTADOR)
        self.assertEqual(papel, "")

    def test_retorna_vazio_quando_root_e_none(self):
        papel = _determinar_papel_nfse(None, CNPJ_PRESTADOR)
        self.assertEqual(papel, "")

    def test_aceita_cnpj_com_namespace_na_tag(self):
        """Namespace no elemento não deve impedir a detecção do CNPJ."""
        xml_ns = (
            '<CompNfse xmlns="http://www.sped.fazenda.gov.br/nfse">'
            f'<emit><CNPJ>{CNPJ_PRESTADOR}</CNPJ></emit>'
            '</CompNfse>'
        )
        root = ET.fromstring(xml_ns)
        papel = _determinar_papel_nfse(root, CNPJ_PRESTADOR)
        self.assertEqual(papel, "EMITENTE")

    def test_aceita_secao_prest_alternativa(self):
        """Alguns XML usam <prest> em vez de <emit>."""
        xml_prest = (
            f'<CompNfse>'
            f'<prest><CNPJ>{CNPJ_PRESTADOR}</CNPJ></prest>'
            f'</CompNfse>'
        )
        root = ET.fromstring(xml_prest)
        papel = _determinar_papel_nfse(root, CNPJ_PRESTADOR)
        self.assertEqual(papel, "EMITENTE")

    def test_cnpj_com_pontuacao_no_xml_e_normalizado(self):
        """CNPJ pontuado no XML tem dígitos extraídos → detectado corretamente."""
        xml_cnpj_pont = f"<CompNfse><emit><CNPJ>12.345.678/0001-99</CNPJ></emit></CompNfse>"
        root = ET.fromstring(xml_cnpj_pont)
        # O conector extrai apenas dígitos: "12.345.678/0001-99" → "12345678000199"
        papel = _determinar_papel_nfse(root, CNPJ_PRESTADOR)
        self.assertEqual(papel, "EMITENTE")


# ══════════════════════════════════════════════════════════════════════════════
# 2. _extrair_status_nfse — COMPLETO / CANCELADO / SUBSTITUIDO
# ══════════════════════════════════════════════════════════════════════════════

class TestExtrairStatusNfse(TestCase):

    def _root_cstat(self, cstat: int) -> ET.Element:
        return ET.fromstring(_nfse_xml(cstat=cstat))

    def test_xml_normal_retorna_completo(self):
        root = ET.fromstring(_nfse_xml())
        self.assertEqual(_extrair_status_nfse(root), "COMPLETO")

    def test_root_none_retorna_completo(self):
        self.assertEqual(_extrair_status_nfse(None), "COMPLETO")

    def test_cstat_101_retorna_cancelado(self):
        self.assertEqual(_extrair_status_nfse(self._root_cstat(101)), "CANCELADO")

    def test_cstat_132_retorna_cancelado(self):
        self.assertEqual(_extrair_status_nfse(self._root_cstat(132)), "CANCELADO")

    def test_cstat_150_retorna_substituido(self):
        self.assertEqual(_extrair_status_nfse(self._root_cstat(150)), "SUBSTITUIDO")

    def test_tag_cancnfse_retorna_cancelado(self):
        xml = "<CompNfse><cancNfse><id>1</id></cancNfse></CompNfse>"
        root = ET.fromstring(xml)
        self.assertEqual(_extrair_status_nfse(root), "CANCELADO")

    def test_tag_nfsesubst_retorna_substituido(self):
        xml = "<CompNfse><nfseSubst><chNfseSubst>X</chNfseSubst></nfseSubst></CompNfse>"
        root = ET.fromstring(xml)
        self.assertEqual(_extrair_status_nfse(root), "SUBSTITUIDO")

    def test_cstat_nao_numerico_cai_no_fallback_de_tags(self):
        xml = "<CompNfse><cStat>ativo</cStat></CompNfse>"
        root = ET.fromstring(xml)
        self.assertEqual(_extrair_status_nfse(root), "COMPLETO")


# ══════════════════════════════════════════════════════════════════════════════
# 3. capturar_proximo_lote — estados do protocolo ADN
# ══════════════════════════════════════════════════════════════════════════════

class TestNFSeCapturarProximoLote(TestCase):

    def setUp(self):
        self.cliente = _cliente()

    def _svc(self, payload: dict, status_code: int = 200):
        return _service(self.cliente, _mock_http(payload, status_code))

    # -- UP_TO_DATE ---------------------------------------------------------------

    def test_up_to_date_quando_nsu_ja_e_maximo(self):
        ControleNSU.objects.create(
            cliente=self.cliente, tipo_documento="NFSE",
            ultimo_nsu=50, max_nsu=50,
        )
        svc = _service(self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertEqual(resultado, "UP_TO_DATE")
        svc.con.enviar_requisicao_rest_mtls.assert_not_called()

    def test_nsu_zero_nao_e_up_to_date(self):
        """Estado inicial (NSU=0, max=0) não é UP_TO_DATE — deve consultar ADN."""
        svc = self._svc(_payload_vazio(), status_code=404)
        svc.capturar_proximo_lote()
        svc.con.enviar_requisicao_rest_mtls.assert_called_once()

    # -- VAZIO_AGUARDAR_1H --------------------------------------------------------

    def test_404_com_lote_vazio_retorna_vazio_aguardar_1h(self):
        svc = self._svc(_payload_vazio(), status_code=404)
        self.assertEqual(svc.capturar_proximo_lote(), "VAZIO_AGUARDAR_1H")

    def test_200_com_lote_vazio_retorna_vazio_aguardar_1h(self):
        svc = self._svc(_payload_vazio(), status_code=200)
        self.assertEqual(svc.capturar_proximo_lote(), "VAZIO_AGUARDAR_1H")

    def test_vazio_nao_avanca_nsu(self):
        ControleNSU.objects.create(
            cliente=self.cliente, tipo_documento="NFSE",
            ultimo_nsu=10, max_nsu=10,
        )
        ctrl = ControleNSU.objects.get(cliente=self.cliente, tipo_documento="NFSE")
        ctrl.max_nsu = 99
        ctrl.save()

        svc = self._svc(_payload_vazio(), status_code=404)
        svc.capturar_proximo_lote()

        ctrl.refresh_from_db()
        self.assertEqual(ctrl.ultimo_nsu, 10, "NSU não deve avançar em fila vazia")

    # -- TEM_MAIS_DADOS / FINALIZADO ----------------------------------------------

    def test_tem_mais_dados_quando_ult_menor_que_max(self):
        payload = _payload_adn(ult_nsu=5, max_nsu=10)
        svc = self._svc(payload)
        self.assertEqual(svc.capturar_proximo_lote(), "TEM_MAIS_DADOS")

    def test_finalizado_quando_ult_igual_a_max(self):
        payload = _payload_adn(ult_nsu=10, max_nsu=10)
        svc = self._svc(payload)
        self.assertEqual(svc.capturar_proximo_lote(), "FINALIZADO")

    def test_persiste_nsu_apos_lote(self):
        payload = _payload_adn(ult_nsu=7, max_nsu=20)
        svc = self._svc(payload)
        svc.capturar_proximo_lote()

        ctrl = ControleNSU.objects.get(cliente=self.cliente, tipo_documento="NFSE")
        self.assertEqual(ctrl.ultimo_nsu, 7)
        self.assertEqual(ctrl.max_nsu, 20)

    # -- Erros de rede / protocolo ------------------------------------------------

    def test_erro_conexao_retorna_erro_conexao(self):
        svc = _service(self.cliente)
        svc.con.enviar_requisicao_rest_mtls.side_effect = Exception("mTLS handshake failed")
        self.assertEqual(svc.capturar_proximo_lote(), "ERRO_CONEXAO")

    def test_status_500_retorna_erro_http(self):
        svc = _service(self.cliente, _mock_http({}, status_code=500))
        self.assertEqual(svc.capturar_proximo_lote(), "ERRO_HTTP")

    def test_status_403_retorna_erro_http(self):
        svc = _service(self.cliente, _mock_http({}, status_code=403))
        self.assertEqual(svc.capturar_proximo_lote(), "ERRO_HTTP")

    def test_resposta_nao_json_retorna_xml_invalido(self):
        r = MagicMock()
        r.status_code = 200
        r.text = "<<< isso nao e json"
        svc = _service(self.cliente, r)
        self.assertEqual(svc.capturar_proximo_lote(), "XML_INVALIDO")


# ══════════════════════════════════════════════════════════════════════════════
# 4. Persistência e papel_nfse
# ══════════════════════════════════════════════════════════════════════════════

class TestNFSePersistencia(TestCase):

    def setUp(self):
        self.cliente = _cliente()

    def _svc(self, payload: dict):
        return _service(self.cliente, _mock_http(payload))

    def test_persiste_documento_e_xml_apos_lote(self):
        payload = _payload_adn(chave=CHAVE_44, xml_text=_nfse_xml())
        self._svc(payload).capturar_proximo_lote()

        self.assertEqual(Documento.objects.filter(cliente=self.cliente).count(), 1)
        self.assertEqual(Xml.objects.filter(documento__cliente=self.cliente).count(), 1)

    def test_tipo_documento_salvo_como_nfse(self):
        payload = _payload_adn(chave=CHAVE_44, xml_text=_nfse_xml())
        self._svc(payload).capturar_proximo_lote()
        doc = Documento.objects.get(cliente=self.cliente)
        self.assertEqual(doc.tipo_documento, "NFSE")

    def test_papel_emitente_quando_cnpj_bate(self):
        """Cliente tem o mesmo CNPJ do prestador → EMITENTE."""
        xml = _nfse_xml(prestador_cnpj=CNPJ_PRESTADOR)
        payload = _payload_adn(chave=CHAVE_44, xml_text=xml)
        self._svc(payload).capturar_proximo_lote()
        doc = Documento.objects.get(cliente=self.cliente)
        self.assertEqual(doc.papel_nfse, "EMITENTE")

    def test_papel_tomador_quando_cnpj_diferente(self):
        """Cliente tem CNPJ diferente do prestador → TOMADOR."""
        xml = _nfse_xml(prestador_cnpj=CNPJ_TOMADOR)
        payload = _payload_adn(chave=CHAVE_44, xml_text=xml)
        self._svc(payload).capturar_proximo_lote()
        doc = Documento.objects.get(cliente=self.cliente)
        self.assertEqual(doc.papel_nfse, "TOMADOR")

    def test_chave_50_digitos_e_aceita(self):
        payload = _payload_adn(chave=CHAVE_50, xml_text=_nfse_xml())
        self._svc(payload).capturar_proximo_lote()
        self.assertTrue(Documento.objects.filter(chave=CHAVE_50).exists())

    def test_chave_invalida_e_ignorada_sem_crash(self):
        """Item com chave de tamanho inválido deve ser descartado silenciosamente."""
        payload = _payload_adn(chave="CHAVE_CURTA", xml_text=_nfse_xml())
        self._svc(payload).capturar_proximo_lote()
        self.assertEqual(Documento.objects.filter(cliente=self.cliente).count(), 0)

    def test_xml_vazio_no_item_e_ignorado(self):
        """Item com ArquivoXml vazio deve ser descartado silenciosamente."""
        r = MagicMock()
        r.status_code = 200
        r.text = json.dumps({
            "LoteDFe": [{"NSU": 1, "ChaveAcesso": CHAVE_44, "ArquivoXml": ""}],
            "UltNSU": 1, "MaxNSU": 1,
        })
        svc = _service(self.cliente, r)
        svc.capturar_proximo_lote()
        self.assertEqual(Documento.objects.filter(cliente=self.cliente).count(), 0)

    # -- Idempotência -------------------------------------------------------------

    def test_segundo_lote_com_mesma_chave_nao_duplica_documento(self):
        """get_or_create garante idempotência mesmo que a nota chegue duas vezes."""
        xml = _nfse_xml()
        payload = _payload_adn(chave=CHAVE_44, xml_text=xml, ult_nsu=1, max_nsu=5)
        svc = _service(self.cliente, _mock_http(payload))
        svc.capturar_proximo_lote()

        ControleNSU.objects.filter(cliente=self.cliente, tipo_documento="NFSE").update(
            ultimo_nsu=0, max_nsu=0
        )
        svc.con.enviar_requisicao_rest_mtls.return_value = _mock_http(payload)
        svc.capturar_proximo_lote()

        self.assertEqual(
            Documento.objects.filter(cliente=self.cliente, chave=CHAVE_44).count(),
            1,
            "Idempotência violada: NFS-e duplicada no banco",
        )

    def test_atualizacao_de_papel_em_reprocessamento(self):
        """
        Segunda passagem com papel diferente deve atualizar papel_nfse no banco
        (cenário: primeira captura teve XML inválido, segunda corrigi o papel).
        """
        xml_sem_cnpj = "<CompNfse><emit><xNome>X</xNome></emit></CompNfse>"
        payload1 = _payload_adn(chave=CHAVE_44, xml_text=xml_sem_cnpj)
        svc = _service(self.cliente, _mock_http(payload1))
        svc.capturar_proximo_lote()

        doc = Documento.objects.get(chave=CHAVE_44)
        self.assertEqual(doc.papel_nfse, "")

        # Reprocessa com XML completo
        ControleNSU.objects.filter(cliente=self.cliente, tipo_documento="NFSE").update(
            ultimo_nsu=0, max_nsu=0
        )
        xml_com_cnpj = _nfse_xml(prestador_cnpj=CNPJ_PRESTADOR)
        payload2 = _payload_adn(chave=CHAVE_44, xml_text=xml_com_cnpj)
        svc.con.enviar_requisicao_rest_mtls.return_value = _mock_http(payload2)
        svc.capturar_proximo_lote()

        doc.refresh_from_db()
        self.assertEqual(doc.papel_nfse, "EMITENTE")

    def test_status_cancelado_salvo_no_banco(self):
        xml = _nfse_xml(cstat=101)
        payload = _payload_adn(chave=CHAVE_44, xml_text=xml)
        self._svc(payload).capturar_proximo_lote()
        doc = Documento.objects.get(chave=CHAVE_44)
        self.assertEqual(doc.status, "CANCELADO")
