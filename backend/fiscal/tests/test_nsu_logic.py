"""
Testes determinísticos da lógica de NSU incremental.

Quatro invariantes obrigatórias (nenhuma toca a SEFAZ real):
  1. NSU avança corretamente após resposta 138
  2. Para quando ultNSU == maxNSU (UP_TO_DATE)
  3. Respeita espera de 1h ao receber cStat=137
  4. Responde corretamente a todos os tipos de erro SEFAZ

Cobertura: NFeCapturaService, CTeCapturaService e _esgotar_fila (tasks.py).
"""
import base64
import gzip
from unittest.mock import MagicMock, patch

from django.test import TestCase

from fiscal.conectores.cte import CTeCapturaService
from fiscal.conectores.nfe import NFeCapturaService
from fiscal.models import Cliente, ControleNSU, Documento, Xml
from fiscal.tasks import _esgotar_fila


# ── Helpers de fixture ─────────────────────────────────────────────────────────

def _gz64(xml_text: str) -> str:
    """Gzip-comprime e base64-codifica um XML, exatamente como a SEFAZ envia."""
    return base64.b64encode(gzip.compress(xml_text.encode("utf-8"))).decode("ascii")


def _nfe_inner(chave: str = "35260612345678000199550010000000010000000001",
               emitente: str = "EMITENTE TESTE LTDA",
               valor: str = "500.00") -> str:
    return (
        f'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">'
        f'<NFe><infNFe><ide/><emit><xNome>{emitente}</xNome></emit>'
        f'<det><prod/></det><total><ICMSTot><vNF>{valor}</vNF></ICMSTot></total>'
        f'</infNFe></NFe>'
        f'<protNFe><infProt><chNFe>{chave}</chNFe></infProt></protNFe>'
        f'</nfeProc>'
    )


def _cte_inner(chave: str = "35260612345678000199570010000000010000000001",
               emitente: str = "TRANSPORTADORA TESTE LTDA",
               valor: str = "300.00") -> str:
    return (
        f'<cteProc xmlns="http://www.portalfiscal.inf.br/cte">'
        f'<CTe><infCte><ide/><emit><xNome>{emitente}</xNome></emit>'
        f'<vPrest><vTPrest>{valor}</vTPrest></vPrest>'
        f'</infCte></CTe>'
        f'<protCTe><infProt><chCTe>{chave}</chCTe></infProt></protCTe>'
        f'</cteProc>'
    )


def _xml_138(ult_nsu: int, max_nsu: int, docs: list[tuple[int, str]],
             ns: str = "http://www.portalfiscal.inf.br/nfe") -> str:
    """
    Monta envelope retDistDFeInt com cStat=138.
    docs: lista de (nsu_int, xml_inner_str).
    """
    docs_block = "".join(
        f'<docZip NSU="{str(nsu).zfill(15)}" schema="...">{_gz64(inner)}</docZip>'
        for nsu, inner in docs
    )
    return (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<retDistDFeInt versao="1.01" xmlns="{ns}">'
        f'<tpAmb>2</tpAmb>'
        f'<cStat>138</cStat>'
        f'<xMotivo>Documentos localizados</xMotivo>'
        f'<ultNSU>{str(ult_nsu).zfill(15)}</ultNSU>'
        f'<maxNSU>{str(max_nsu).zfill(15)}</maxNSU>'
        f'<loteDistDFeInt>{docs_block}</loteDistDFeInt>'
        f'</retDistDFeInt>'
    )


def _xml_137(ns: str = "http://www.portalfiscal.inf.br/nfe") -> str:
    return (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<retDistDFeInt versao="1.01" xmlns="{ns}">'
        f'<tpAmb>2</tpAmb>'
        f'<cStat>137</cStat>'
        f'<xMotivo>Nenhum documento localizado</xMotivo>'
        f'</retDistDFeInt>'
    )


def _xml_sem_cstat() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">'
        '<tpAmb>2</tpAmb>'
        '</retDistDFeInt>'
    )


def _xml_rejeicao() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">'
        '<cStat>999</cStat>'
        '<xMotivo>Rejeicao: CNPJ do solicitante invalido</xMotivo>'
        '</retDistDFeInt>'
    )


def _mock_resposta(xml_text: str, status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = xml_text
    return r


# ── Base comum ─────────────────────────────────────────────────────────────────

class _BaseNSU(TestCase):
    """
    TestCase base com um cliente de teste.
    Subclasses definem `ServiceClass`, `tipo_doc` e `_inner_xml()`.
    """
    ServiceClass = None
    tipo_doc = None

    @classmethod
    def _inner_xml(cls, chave=None, **kw) -> str:
        raise NotImplementedError

    @classmethod
    def _consulta_method(cls):
        raise NotImplementedError

    def setUp(self):
        self.cliente = Cliente.objects.create(
            cnpj="12345678000199",
            razao_social="Empresa Teste LTDA",
            uf="SP",
        )

    def _service(self, conector):
        return self.ServiceClass(conector_sefaz=conector, cliente=self.cliente)

    def _controle(self):
        return ControleNSU.objects.get(
            cliente=self.cliente, tipo_documento=self.tipo_doc
        )


# ══════════════════════════════════════════════════════════════════════════════
# 1. NFe — lógica de NSU
# ══════════════════════════════════════════════════════════════════════════════

class TestNFeNSULogica(_BaseNSU):
    ServiceClass = NFeCapturaService
    tipo_doc = "NFE"

    @classmethod
    def _inner_xml(cls, chave="35260612345678000199550010000000010000000001", **kw):
        return _nfe_inner(chave=chave, **kw)

    # ── Invariante 1: NSU avança ───────────────────────────────────────────────

    def test_nsu_inicial_zero_nao_dispara_short_circuit(self):
        """NSU=0/max=0 no primeiro uso: deve chamar a SEFAZ, não retornar UP_TO_DATE."""
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(_xml_137())

        resultado = self._service(conector).capturar_proximo_lote()

        conector.consulta_notas_cnpj.assert_called_once()
        self.assertNotEqual(resultado, "UP_TO_DATE")

    def test_138_tem_mais_dados_quando_ult_menor_que_max(self):
        """cStat=138 com ultNSU(150) < maxNSU(200) → TEM_MAIS_DADOS."""
        xml = _xml_138(150, 200, [(150, self._inner_xml())])
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(xml)

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "TEM_MAIS_DADOS")

    def test_138_finalizado_quando_ult_igual_max(self):
        """cStat=138 com ultNSU==maxNSU → FINALIZADO (fila esgotada neste lote)."""
        xml = _xml_138(200, 200, [(200, self._inner_xml())])
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(xml)

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "FINALIZADO")

    def test_138_persiste_nsu_no_banco(self):
        """Após 138, ultimo_nsu e max_nsu devem refletir os valores da SEFAZ."""
        xml = _xml_138(150, 200, [(150, self._inner_xml())])
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(xml)

        self._service(conector).capturar_proximo_lote()

        ctrl = self._controle()
        self.assertEqual(ctrl.ultimo_nsu, 150)
        self.assertEqual(ctrl.max_nsu, 200)
        self.assertIsNotNone(ctrl.atualizado_em)

    # ── Invariante 2: Para quando ultNSU == maxNSU ────────────────────────────

    def test_up_to_date_nao_chama_sefaz(self):
        """Se ultimo_nsu > 0 e == max_nsu, não deve chamar a SEFAZ."""
        ControleNSU.objects.create(
            cliente=self.cliente,
            tipo_documento=self.tipo_doc,
            ultimo_nsu=200,
            max_nsu=200,
        )
        conector = MagicMock()

        resultado = self._service(conector).capturar_proximo_lote()

        conector.consulta_notas_cnpj.assert_not_called()
        self.assertEqual(resultado, "UP_TO_DATE")

    def test_nsu_zero_com_max_zero_nao_e_up_to_date(self):
        """NSU=0 e max=0 (estado inicial) não deve ser tratado como UP_TO_DATE."""
        ControleNSU.objects.create(
            cliente=self.cliente,
            tipo_documento=self.tipo_doc,
            ultimo_nsu=0,
            max_nsu=0,
        )
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(_xml_137())

        self._service(conector).capturar_proximo_lote()

        # Deve ter chamado a SEFAZ
        conector.consulta_notas_cnpj.assert_called_once()

    # ── Invariante 3: cStat=137, espera de 1h ─────────────────────────────────

    def test_137_retorna_vazio_aguardar_1h(self):
        """cStat=137 → deve retornar VAZIO_AGUARDAR_1H."""
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(_xml_137())

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "VAZIO_AGUARDAR_1H")

    def test_137_nao_avanca_nsu(self):
        """cStat=137 não deve alterar ultimo_nsu (só atualiza timestamp)."""
        ControleNSU.objects.create(
            cliente=self.cliente,
            tipo_documento=self.tipo_doc,
            ultimo_nsu=50,
            max_nsu=50,
        )
        # Forçar re-consulta: simula que o max_nsu mudou externamente
        ctrl = ControleNSU.objects.get(cliente=self.cliente, tipo_documento=self.tipo_doc)
        ctrl.max_nsu = 100  # agora tem mais, mas a SEFAZ devolveu 137
        ctrl.save()

        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(_xml_137())

        self._service(conector).capturar_proximo_lote()

        ctrl.refresh_from_db()
        self.assertEqual(ctrl.ultimo_nsu, 50, "NSU não deve avançar em resposta 137")

    # ── Invariante 4: Erros SEFAZ ─────────────────────────────────────────────

    def test_erro_conexao_retorna_erro_conexao(self):
        """Exceção na chamada ao conector → ERRO_CONEXAO (sem propagar a exceção)."""
        conector = MagicMock()
        conector.consulta_notas_cnpj.side_effect = Exception("timeout na conexão mTLS")

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "ERRO_CONEXAO")

    def test_erro_http_status_500_retorna_erro_http(self):
        """status_code != 200 → ERRO_HTTP."""
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta("", status_code=500)

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "ERRO_HTTP")

    def test_xml_sem_cstat_retorna_xml_invalido(self):
        """XML válido mas sem elemento cStat → XML_INVALIDO."""
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(_xml_sem_cstat())

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "XML_INVALIDO")

    def test_xml_corrompido_retorna_xml_corrompido(self):
        """XML não-parseável → XML_CORROMPIDO (não propaga ParseError)."""
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta("<<< isso nao e xml")

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "XML_CORROMPIDO")

    def test_cstat_desconhecido_retorna_rejeitado(self):
        """cStat diferente de 137/138 → REJEITADO."""
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(_xml_rejeicao())

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "REJEITADO")

    # ── Persistência e idempotência ───────────────────────────────────────────

    def test_138_persiste_documento_e_xml(self):
        """Após resposta 138 com 1 docZip, deve existir 1 Documento e 1 Xml no banco."""
        chave = "35260612345678000199550010000000010000000001"
        xml = _xml_138(50, 50, [(50, self._inner_xml(chave=chave))])
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(xml)

        self._service(conector).capturar_proximo_lote()

        self.assertEqual(Documento.objects.filter(cliente=self.cliente).count(), 1)
        self.assertEqual(Xml.objects.filter(documento__cliente=self.cliente).count(), 1)

    def test_idempotencia_segundo_lote_com_mesma_chave_nao_duplica(self):
        """Mesmo docZip recebido duas vezes: get_or_create garante apenas 1 Documento."""
        chave = "35260612345678000199550010000000010000000002"
        xml = _xml_138(50, 100, [(50, self._inner_xml(chave=chave))])
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = _mock_resposta(xml)

        svc = self._service(conector)
        svc.capturar_proximo_lote()
        # Reseta NSU para forçar re-consulta
        ControleNSU.objects.filter(cliente=self.cliente, tipo_documento=self.tipo_doc).update(
            ultimo_nsu=0, max_nsu=0
        )
        svc.capturar_proximo_lote()

        self.assertEqual(
            Documento.objects.filter(cliente=self.cliente, chave=chave).count(),
            1,
            "Idempotência violada: documento duplicado",
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. CTe — mesma lógica de NSU, diferentes campos XML
# ══════════════════════════════════════════════════════════════════════════════

class TestCTeNSULogica(_BaseNSU):
    ServiceClass = CTeCapturaService
    tipo_doc = "CTE"

    @classmethod
    def _inner_xml(cls, chave="35260612345678000199570010000000010000000001", **kw):
        return _cte_inner(chave=chave, **kw)

    def test_138_tem_mais_dados(self):
        xml = _xml_138(150, 200, [(150, self._inner_xml())])
        conector = MagicMock()
        conector.consulta_ctes_cnpj.return_value = _mock_resposta(xml)

        resultado = self._service(conector).capturar_proximo_lote()

        self.assertEqual(resultado, "TEM_MAIS_DADOS")

    def test_138_persiste_nsu_no_banco(self):
        xml = _xml_138(150, 200, [(150, self._inner_xml())])
        conector = MagicMock()
        conector.consulta_ctes_cnpj.return_value = _mock_resposta(xml)

        self._service(conector).capturar_proximo_lote()

        ctrl = self._controle()
        self.assertEqual(ctrl.ultimo_nsu, 150)
        self.assertEqual(ctrl.max_nsu, 200)

    def test_up_to_date_nao_chama_sefaz(self):
        ControleNSU.objects.create(
            cliente=self.cliente, tipo_documento=self.tipo_doc,
            ultimo_nsu=200, max_nsu=200,
        )
        conector = MagicMock()
        resultado = self._service(conector).capturar_proximo_lote()
        conector.consulta_ctes_cnpj.assert_not_called()
        self.assertEqual(resultado, "UP_TO_DATE")

    def test_137_retorna_vazio_aguardar_1h(self):
        conector = MagicMock()
        conector.consulta_ctes_cnpj.return_value = _mock_resposta(_xml_137())
        resultado = self._service(conector).capturar_proximo_lote()
        self.assertEqual(resultado, "VAZIO_AGUARDAR_1H")

    def test_137_nao_avanca_nsu(self):
        ControleNSU.objects.create(
            cliente=self.cliente, tipo_documento=self.tipo_doc,
            ultimo_nsu=80, max_nsu=80,
        )
        ctrl = ControleNSU.objects.get(cliente=self.cliente, tipo_documento=self.tipo_doc)
        ctrl.max_nsu = 100
        ctrl.save()

        conector = MagicMock()
        conector.consulta_ctes_cnpj.return_value = _mock_resposta(_xml_137())
        self._service(conector).capturar_proximo_lote()

        ctrl.refresh_from_db()
        self.assertEqual(ctrl.ultimo_nsu, 80)

    def test_erro_conexao(self):
        conector = MagicMock()
        conector.consulta_ctes_cnpj.side_effect = Exception("SSL handshake failed")
        resultado = self._service(conector).capturar_proximo_lote()
        self.assertEqual(resultado, "ERRO_CONEXAO")

    def test_xml_corrompido(self):
        conector = MagicMock()
        conector.consulta_ctes_cnpj.return_value = _mock_resposta("nao e xml <<<")
        resultado = self._service(conector).capturar_proximo_lote()
        self.assertEqual(resultado, "XML_CORROMPIDO")

    def test_idempotencia(self):
        chave = "35260612345678000199570010000000010000000099"
        xml = _xml_138(50, 100, [(50, self._inner_xml(chave=chave))])
        conector = MagicMock()
        conector.consulta_ctes_cnpj.return_value = _mock_resposta(xml)

        svc = self._service(conector)
        svc.capturar_proximo_lote()
        ControleNSU.objects.filter(cliente=self.cliente, tipo_documento=self.tipo_doc).update(
            ultimo_nsu=0, max_nsu=0
        )
        svc.capturar_proximo_lote()

        self.assertEqual(
            Documento.objects.filter(cliente=self.cliente, chave=chave).count(), 1
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. _esgotar_fila (tasks.py) — controle do loop
# ══════════════════════════════════════════════════════════════════════════════

class TestEsgotarFila(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            cnpj="99999999000191",
            razao_social="Loop Teste LTDA",
            uf="RJ",
        )

    def _mock_service(self, sequencia: list[str]) -> MagicMock:
        svc = MagicMock()
        svc.capturar_proximo_lote.side_effect = sequencia
        return svc

    def test_para_no_vazio_aguardar_1h(self):
        """Loop deve parar ao receber VAZIO_AGUARDAR_1H e não tentar mais."""
        svc = self._mock_service(["VAZIO_AGUARDAR_1H"])
        resultado = _esgotar_fila(svc, self.cliente, "NFE")
        self.assertEqual(resultado, "VAZIO_AGUARDAR_1H")
        self.assertEqual(svc.capturar_proximo_lote.call_count, 1)

    def test_para_no_up_to_date(self):
        """Loop deve parar ao receber UP_TO_DATE."""
        svc = self._mock_service(["UP_TO_DATE"])
        resultado = _esgotar_fila(svc, self.cliente, "NFE")
        self.assertEqual(resultado, "UP_TO_DATE")
        self.assertEqual(svc.capturar_proximo_lote.call_count, 1)

    def test_itera_enquanto_tem_mais_dados(self):
        """TEM_MAIS_DADOS mantém o loop; FINALIZADO encerra."""
        svc = self._mock_service([
            "TEM_MAIS_DADOS",
            "TEM_MAIS_DADOS",
            "FINALIZADO",
        ])
        resultado = _esgotar_fila(svc, self.cliente, "NFE")
        self.assertEqual(resultado, "FINALIZADO")
        self.assertEqual(svc.capturar_proximo_lote.call_count, 3)

    def test_teto_maximo_de_lotes_evita_loop_infinito(self):
        """
        Se a SEFAZ continuar respondendo TEM_MAIS_DADOS indefinidamente,
        _esgotar_fila deve parar no teto _MAX_LOTES_POR_CLIENTE (= 5).
        """
        svc = self._mock_service(["TEM_MAIS_DADOS"] * 10)
        _esgotar_fila(svc, self.cliente, "NFE")
        # O teto é 5 — não deve ter chamado mais do que isso
        from fiscal.tasks import _MAX_LOTES_POR_CLIENTE
        self.assertLessEqual(svc.capturar_proximo_lote.call_count, _MAX_LOTES_POR_CLIENTE)

    def test_para_no_erro_conexao(self):
        """ERRO_CONEXAO encerra o loop sem explodir."""
        svc = self._mock_service(["TEM_MAIS_DADOS", "ERRO_CONEXAO"])
        resultado = _esgotar_fila(svc, self.cliente, "NFE")
        self.assertEqual(resultado, "ERRO_CONEXAO")
        self.assertEqual(svc.capturar_proximo_lote.call_count, 2)

    def test_sequencia_tem_mais_depois_vazio(self):
        """
        Sequência realista: dois lotes com dados, depois fila esgota.
        Deve iterar exatamente 3 vezes.
        """
        svc = self._mock_service([
            "TEM_MAIS_DADOS",
            "TEM_MAIS_DADOS",
            "VAZIO_AGUARDAR_1H",
        ])
        resultado = _esgotar_fila(svc, self.cliente, "CTE")
        self.assertEqual(resultado, "VAZIO_AGUARDAR_1H")
        self.assertEqual(svc.capturar_proximo_lote.call_count, 3)
