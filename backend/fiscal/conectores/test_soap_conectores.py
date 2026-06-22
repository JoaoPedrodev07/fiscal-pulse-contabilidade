"""
TDD — Testes do conector SOAP NF-e e CT-e em ConectorSefaz.

Filosofia: cada teste verifica UM comportamento observável.
Os mocks cobrem requests.post para isolar da SEFAZ real.
"""
import base64
import gzip
from unittest.mock import MagicMock, patch

from django.test import TestCase

from fiscal.conectores.fabrica import ConectorSefaz, _extrair_conteudo_soap

# ── Helpers ──────────────────────────────────────────────────────────────────


def _soap_resp_138(tipo: str = 'nfe') -> str:
    """Resposta SOAP cStat=138 (tem documentos) para NF-e ou CT-e."""
    ns = f'http://www.portalfiscal.inf.br/{tipo}'
    inner = (
        f'<retDistDFeInt versao="1.01" xmlns="{ns}">'
        '<tpAmb>1</tpAmb><cStat>138</cStat>'
        '<xMotivo>Documentos localizados</xMotivo>'
        '<ultNSU>000000000000100</ultNSU>'
        '<maxNSU>000000000000200</maxNSU>'
        '</retDistDFeInt>'
    )
    return _embrulhar_soap(inner)


def _soap_resp_137() -> str:
    """Resposta SOAP cStat=137 (fila vazia)."""
    inner = (
        '<retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">'
        '<tpAmb>1</tpAmb><cStat>137</cStat>'
        '<xMotivo>Nenhum documento localizado</xMotivo>'
        '<ultNSU>000000000000050</ultNSU>'
        '<maxNSU>000000000000050</maxNSU>'
        '</retDistDFeInt>'
    )
    return _embrulhar_soap(inner)


def _embrulhar_soap(inner_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
        '<soap12:Body>'
        '<nfeDadosMsgResult>'
        f'{inner_xml}'
        '</nfeDadosMsgResult>'
        '</soap12:Body>'
        '</soap12:Envelope>'
    )


def _make_conector(homologacao: bool = True) -> ConectorSefaz:
    """Cria ConectorSefaz com PFX fictício (não é usado em testes com mock)."""
    return ConectorSefaz(
        pfx_bytes=b'fake',
        senha='fake',
        uf='sp',
        codigo_uf=35,
        homologacao=homologacao,
    )


# ── 1. Extração de conteúdo SOAP ─────────────────────────────────────────────


class ExtrairConteudoSoapTest(TestCase):

    def test_extrai_retdistdfeint_do_envelope_soap(self):
        soap = _soap_resp_138('nfe')
        resultado = _extrair_conteudo_soap(soap)
        self.assertIn('cStat', resultado)
        self.assertIn('138', resultado)

    def test_retorna_xml_bruto_se_nao_for_soap(self):
        xml_bruto = '<retDistDFeInt><cStat>137</cStat></retDistDFeInt>'
        resultado = _extrair_conteudo_soap(xml_bruto)
        self.assertIn('cStat', resultado)

    def test_retorna_texto_original_quando_xml_invalido(self):
        texto_invalido = 'not xml at all'
        resultado = _extrair_conteudo_soap(texto_invalido)
        self.assertEqual(resultado, texto_invalido)


# ── 2. NF-e SOAP distNSU ─────────────────────────────────────────────────────


class ConsultaNotasCnpjTest(TestCase):

    def setUp(self):
        self.conector = _make_conector(homologacao=True)

    def _mock_post(self, texto_resposta: str, status: int = 200):
        mock_resp = MagicMock()
        mock_resp.status_code = status
        mock_resp.text = texto_resposta
        return mock_resp

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_retorna_adapter_com_status_200_e_cstat_138(self, mock_pem, mock_post):
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_138())

        resp = self.conector.consulta_notas_cnpj(cnpj='12345678000199', nsu=0)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('cStat', resp.text)

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_envelope_contem_cnpj_correto(self, mock_pem, mock_post):
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_137())

        self.conector.consulta_notas_cnpj(cnpj='12345678000199', nsu=0)

        args, kwargs = mock_post.call_args
        body = kwargs.get('data', b'').decode('utf-8') if isinstance(kwargs.get('data'), bytes) else kwargs.get('data', '')
        self.assertIn('12345678000199', body)

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_envelope_contem_nsu_formatado_15_digitos(self, mock_pem, mock_post):
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_137())

        self.conector.consulta_notas_cnpj(cnpj='12345678000199', nsu=42)

        _, kwargs = mock_post.call_args
        body = kwargs.get('data', b'').decode('utf-8') if isinstance(kwargs.get('data'), bytes) else kwargs.get('data', '')
        self.assertIn('000000000000042', body)

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_usa_url_homologacao_quando_flag_ligada(self, mock_pem, mock_post):
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_137())

        self.conector.consulta_notas_cnpj(cnpj='12345678000199', nsu=0)

        args, _ = mock_post.call_args
        url = args[0] if args else mock_post.call_args.kwargs.get('url', '')
        self.assertIn('hom', url.lower())

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_usa_url_producao_quando_flag_desligada(self, mock_pem, mock_post):
        conector_prod = _make_conector(homologacao=False)
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_137())

        conector_prod.consulta_notas_cnpj(cnpj='12345678000199', nsu=0)

        args, _ = mock_post.call_args
        url = args[0] if args else mock_post.call_args.kwargs.get('url', '')
        self.assertNotIn('hom', url.lower())

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_propaga_excecao_de_conexao(self, mock_pem, mock_post):
        import requests as req_lib
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.side_effect = req_lib.exceptions.ConnectionError('timeout')

        with self.assertRaises(req_lib.exceptions.ConnectionError):
            self.conector.consulta_notas_cnpj(cnpj='12345678000199', nsu=0)

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_envelope_contem_codigo_uf_35_para_sp(self, mock_pem, mock_post):
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_137())

        self.conector.consulta_notas_cnpj(cnpj='12345678000199', nsu=0)

        _, kwargs = mock_post.call_args
        body = kwargs.get('data', b'').decode('utf-8') if isinstance(kwargs.get('data'), bytes) else kwargs.get('data', '')
        self.assertIn('35', body)


# ── 3. CT-e SOAP distNSU ─────────────────────────────────────────────────────


class ConsultaCtesCnpjTest(TestCase):

    def setUp(self):
        self.conector = _make_conector(homologacao=True)

    def _mock_post(self, texto_resposta: str, status: int = 200):
        mock_resp = MagicMock()
        mock_resp.status_code = status
        mock_resp.text = texto_resposta
        return mock_resp

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_retorna_adapter_status_200_com_cstat_138(self, mock_pem, mock_post):
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_138('cte'))

        resp = self.conector.consulta_ctes_cnpj(cnpj='12345678000199', nsu=0)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('cStat', resp.text)

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_envelope_cte_contem_cnpj(self, mock_pem, mock_post):
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_138('cte'))

        self.conector.consulta_ctes_cnpj(cnpj='99888777000166', nsu=10)

        _, kwargs = mock_post.call_args
        body = kwargs.get('data', b'').decode('utf-8') if isinstance(kwargs.get('data'), bytes) else kwargs.get('data', '')
        self.assertIn('99888777000166', body)

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_usa_url_cte_diferente_de_nfe(self, mock_pem, mock_post):
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = self._mock_post(_soap_resp_138('cte'))

        self.conector.consulta_ctes_cnpj(cnpj='12345678000199', nsu=0)

        args, _ = mock_post.call_args
        url = args[0] if args else mock_post.call_args.kwargs.get('url', '')
        self.assertIn('cte', url.lower())

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_propaga_excecao_de_conexao_cte(self, mock_pem, mock_post):
        import requests as req_lib
        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.side_effect = req_lib.exceptions.ConnectionError('refused')

        with self.assertRaises(req_lib.exceptions.ConnectionError):
            self.conector.consulta_ctes_cnpj(cnpj='12345678000199', nsu=0)


# ── 4. Integração: NFeCaptura recebe resposta do conector SOAP ───────────────


class IntegracaoNFeCapturaComConectorSoapTest(TestCase):
    """
    Garante que NFeCapturaService processa corretamente a resposta
    quando o conector SOAP retorna cStat=137 (fila vazia).
    """

    def setUp(self):
        from fiscal.models import Cliente
        self.cliente = Cliente.objects.create(
            razao_social='Empresa Soap Teste',
            cnpj='11222333000144',
            uf='SP',
        )

    @patch('fiscal.conectores.fabrica.requests.post')
    @patch('fiscal.conectores.fabrica.ConectorSefaz._extrair_pem_temp')
    def test_nfe_service_retorna_vazio_aguardar_quando_cstat_137(self, mock_pem, mock_post):
        from fiscal.conectores.nfe import NFeCapturaService

        mock_pem.return_value.__enter__ = lambda s: ('cert.pem', 'key.pem')
        mock_pem.return_value.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = MagicMock(status_code=200, text=_soap_resp_137())

        conector = _make_conector(homologacao=True)
        # substitui _extrair_pem_temp para que a chamada requests.post não precise do PFX real
        service = NFeCapturaService(conector_sefaz=conector, cliente=self.cliente)

        # Para esse teste, mockamos consulta_notas_cnpj diretamente
        from fiscal.conectores.fabrica import _RespostaAdapter
        xml_inner = _extrair_conteudo_soap(_soap_resp_137())
        conector.consulta_notas_cnpj = MagicMock(return_value=_RespostaAdapter(xml_inner))

        resultado = service.capturar_proximo_lote()
        self.assertEqual(resultado, 'VAZIO_AGUARDAR_1H')
