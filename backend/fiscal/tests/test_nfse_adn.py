"""
Testes determinísticos — NFSeADNCapturaService.

Invariantes verificadas:
  1. NSU avanca e para em maxNSU
  2. get_or_create nao duplica documentos (idempotencia)
  3. tipoPapel (EMITENTE | TOMADOR) e gravado em metadados['papel_nfse']
  4. Erros do ADN sao tratados e logados sem derrubar o worker
  5. Lista vazia → VAZIO_AGUARDAR_1H; NSU nao avanca (real ADN nao retorna ultNSU vazio)
  6. HTTP 404 com JSON valido e resposta normal (fila vazia) -- auditado 2026-06-18

Campos reais da API ADN (auditados em homologacao 2026-06-18):
  Payload com docs:  {"LoteDFe": [...], "ultNSU": N, "maxNSU": N, ...}
  Payload sem docs:  {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO",
                      "LoteDFe": [], "Erros": [...], "TipoAmbiente": "HOMOLOGACAO"}
  HTTP status: 404 quando vazio, 200 quando ha documentos (inferido -- nao auditado com docs)

NUNCA chama o ADN real -- todo HTTP e substituido por _MockConectorADN.
"""
import json
from unittest.mock import patch

from django.test import TestCase

from fiscal.conectores.nfse import NFSeADNCapturaService
from fiscal.models import Cliente, ControleNSU, Documento, Xml


# -- Helpers de fixture -------------------------------------------------------

class _MockResponse:
    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self.text = json.dumps(body) if isinstance(body, dict) else body


class _MockConectorADN:
    """Substitui ConectorSefaz.enviar_requisicao_rest_mtls em todos os testes."""

    def __init__(self, respostas: list):
        self._respostas = list(respostas)
        self.urls_chamadas: list[str] = []

    def enviar_requisicao_rest_mtls(self, url: str, metodo: str = 'GET') -> _MockResponse:
        self.urls_chamadas.append(url)
        if not self._respostas:
            raise RuntimeError('_MockConectorADN: sem mais respostas configuradas')
        return self._respostas.pop(0)


def _resp_ok(lista_dfe: list, ult_nsu: int, max_nsu: int) -> _MockResponse:
    """HTTP 200 com documentos -- campo real e LoteDFe."""
    return _MockResponse(200, {'LoteDFe': lista_dfe, 'ultNSU': ult_nsu, 'maxNSU': max_nsu})


def _resp_vazia() -> _MockResponse:
    """
    HTTP 404 com fila vazia -- corresponde ao payload real auditado no ADN.
    Nao inclui ultNSU/maxNSU porque o ADN nao os retorna neste caso.
    """
    return _MockResponse(404, {
        'StatusProcessamento': 'NENHUM_DOCUMENTO_LOCALIZADO',
        'LoteDFe': [],
        'Alertas': [],
        'Erros': [{'Codigo': 'E2220', 'Descricao': 'Nenhum documento localizado.'}],
        'TipoAmbiente': 'HOMOLOGACAO',
    })


def _item(nsu: int, chave: str, tipo_papel: str = 'TOMADOR', xml_str: str = '') -> dict:
    return {
        'nsu': nsu,
        'chDFe': chave,
        'xml': xml_str or f'<nfse><infNFSe><chNFSe>{chave}</chNFSe></infNFSe></nfse>',
        'tipoPapel': tipo_papel,
    }


CHAVE_1 = '35260612345678000199550010000000010000000001'
CHAVE_2 = '35260612345678000199550010000000020000000002'


def _make_cliente() -> Cliente:
    return Cliente.objects.create(
        cnpj='12345678000199',
        razao_social='Empresa Teste LTDA',
        uf='SP',
    )


# -- Testes -------------------------------------------------------------------

class TestNFSeADNNSULogica(TestCase):

    def setUp(self):
        self.cliente = _make_cliente()

    # 1. short-circuit UP_TO_DATE
    def test_up_to_date_nao_chama_adn(self):
        ControleNSU.objects.create(
            cliente=self.cliente, tipo_documento='NFSE',
            ultimo_nsu=10, max_nsu=10,
        )
        conector = _MockConectorADN([])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertEqual(resultado, 'UP_TO_DATE')
        self.assertEqual(len(conector.urls_chamadas), 0)

    # 2. NSU inicial zero nao dispara UP_TO_DATE
    def test_nsu_inicial_zero_nao_e_up_to_date(self):
        conector = _MockConectorADN([_resp_vazia()])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertIn(resultado, ('VAZIO_AGUARDAR_1H', 'FINALIZADO'))
        self.assertEqual(len(conector.urls_chamadas), 1)

    # 3. Lista vazia → VAZIO_AGUARDAR_1H (HTTP 404 real do ADN)
    def test_lista_vazia_retorna_vazio_aguardar_1h(self):
        conector = _MockConectorADN([_resp_vazia()])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertEqual(resultado, 'VAZIO_AGUARDAR_1H')

    # 4. HTTP 404 com JSON valido NAO e ERRO_HTTP
    def test_http_404_com_json_valido_nao_e_erro_http(self):
        conector = _MockConectorADN([_resp_vazia()])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertNotEqual(resultado, 'ERRO_HTTP')

    # 5. Com dados e ult < max → TEM_MAIS_DADOS
    def test_tem_mais_dados_quando_ult_menor_que_max(self):
        conector = _MockConectorADN([
            _resp_ok([_item(1, CHAVE_1)], ult_nsu=1, max_nsu=50)
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertEqual(resultado, 'TEM_MAIS_DADOS')

    # 6. Com dados e ult == max → FINALIZADO
    def test_finalizado_quando_ult_igual_max(self):
        conector = _MockConectorADN([
            _resp_ok([_item(5, CHAVE_1)], ult_nsu=5, max_nsu=5)
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertEqual(resultado, 'FINALIZADO')

    # 7. NSU e persistido no banco apos lote com documentos
    def test_nsu_avanca_no_banco_apos_lote(self):
        conector = _MockConectorADN([
            _resp_ok([_item(7, CHAVE_1)], ult_nsu=7, max_nsu=20)
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        controle = ControleNSU.objects.get(cliente=self.cliente, tipo_documento='NFSE')
        self.assertEqual(controle.ultimo_nsu, 7)
        self.assertEqual(controle.max_nsu, 20)

    # 8. NSU NAO avanca em lista vazia (ADN real nao retorna ultNSU neste caso)
    def test_nsu_nao_avanca_em_lista_vazia(self):
        conector = _MockConectorADN([_resp_vazia()])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        controle = ControleNSU.objects.get(cliente=self.cliente, tipo_documento='NFSE')
        self.assertEqual(controle.ultimo_nsu, 0)  # nao avancou

    # 9. Documento e XML criados
    def test_persiste_documento_e_xml(self):
        xml_str = (
            '<nfse><infNFSe>'
            f'<chNFSe>{CHAVE_1}</chNFSe>'
            '<xNome>Empresa Prestadora</xNome>'
            '<vServicos>1500.00</vServicos>'
            '</infNFSe></nfse>'
        )
        conector = _MockConectorADN([
            _resp_ok([_item(1, CHAVE_1, xml_str=xml_str)], ult_nsu=1, max_nsu=1)
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        self.assertEqual(Documento.objects.filter(chave=CHAVE_1).count(), 1)
        doc = Documento.objects.get(chave=CHAVE_1)
        self.assertEqual(doc.tipo_documento, 'NFSE')
        self.assertEqual(doc.status, 'COMPLETO')
        self.assertTrue(Xml.objects.filter(documento=doc).exists())

    # 10. Idempotencia — segunda execucao nao duplica
    def test_idempotencia_nao_duplica_documento(self):
        conector = _MockConectorADN([
            _resp_ok([_item(1, CHAVE_1)], ult_nsu=1, max_nsu=1),
            _resp_ok([_item(1, CHAVE_1)], ult_nsu=1, max_nsu=1),
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()
        svc.capturar_proximo_lote()

        self.assertEqual(Documento.objects.filter(chave=CHAVE_1).count(), 1)
        self.assertEqual(Xml.objects.filter(documento__chave=CHAVE_1).count(), 1)

    # 11. TOMADOR salvo em campo de modelo e metadados
    def test_papel_tomador_salvo_em_campo_e_metadados(self):
        conector = _MockConectorADN([
            _resp_ok([_item(1, CHAVE_1, tipo_papel='TOMADOR')], ult_nsu=1, max_nsu=1)
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        doc = Documento.objects.get(chave=CHAVE_1)
        self.assertEqual(doc.papel_nfse, 'TOMADOR')
        self.assertEqual(doc.metadados.get('papel_nfse'), 'TOMADOR')

    # 12. EMITENTE salvo em campo de modelo e metadados
    def test_papel_emitente_salvo_em_campo_e_metadados(self):
        conector = _MockConectorADN([
            _resp_ok([_item(2, CHAVE_2, tipo_papel='EMITENTE')], ult_nsu=2, max_nsu=2)
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        doc = Documento.objects.get(chave=CHAVE_2)
        self.assertEqual(doc.papel_nfse, 'EMITENTE')
        self.assertEqual(doc.metadados.get('papel_nfse'), 'EMITENTE')

    # 13. NSU salvo em metadados do documento
    def test_nsu_salvo_em_metadados(self):
        conector = _MockConectorADN([
            _resp_ok([_item(42, CHAVE_1)], ult_nsu=42, max_nsu=42)
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        doc = Documento.objects.get(chave=CHAVE_1)
        self.assertEqual(doc.metadados.get('nsu'), 42)

    # 14. Lote com dois documentos distintos — ambos persistidos
    def test_lote_com_dois_documentos_persiste_ambos(self):
        conector = _MockConectorADN([
            _resp_ok(
                [_item(1, CHAVE_1, 'TOMADOR'), _item(2, CHAVE_2, 'EMITENTE')],
                ult_nsu=2, max_nsu=2
            )
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        self.assertEqual(Documento.objects.count(), 2)

    # 15. Item com chave invalida e ignorado sem derrubar o lote
    def test_item_com_chave_invalida_ignorado(self):
        conector = _MockConectorADN([
            _resp_ok(
                [
                    {'nsu': 1, 'chDFe': 'CHAVE_CURTA', 'xml': '<nfse/>', 'tipoPapel': 'TOMADOR'},
                    _item(2, CHAVE_2),
                ],
                ult_nsu=2, max_nsu=2
            )
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()

        self.assertIn(resultado, ('FINALIZADO', 'TEM_MAIS_DADOS'))
        self.assertEqual(Documento.objects.count(), 1)
        self.assertEqual(Documento.objects.first().chave, CHAVE_2)

    # 16. Item com xml vazio e ignorado sem derrubar o lote
    def test_item_com_xml_vazio_ignorado(self):
        conector = _MockConectorADN([
            _resp_ok(
                [
                    {'nsu': 1, 'chDFe': CHAVE_1, 'xml': '', 'tipoPapel': 'TOMADOR'},
                    _item(2, CHAVE_2),
                ],
                ult_nsu=2, max_nsu=2
            )
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        self.assertEqual(Documento.objects.count(), 1)
        self.assertEqual(Documento.objects.first().chave, CHAVE_2)

    # 17. Erro de conexao (exception no HTTP)
    def test_erro_conexao_retorna_erro_conexao(self):
        class _ConectorQueExplode:
            def enviar_requisicao_rest_mtls(self, url, metodo='GET'):
                raise ConnectionError('timeout mTLS ADN')

        svc = NFSeADNCapturaService(_ConectorQueExplode(), self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertEqual(resultado, 'ERRO_CONEXAO')

    # 18. Erro HTTP inesperado (503) → ERRO_HTTP
    def test_erro_http_503_retorna_erro_http(self):
        conector = _MockConectorADN([_MockResponse(503, 'Service Unavailable')])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertEqual(resultado, 'ERRO_HTTP')

    # 19. Resposta nao-JSON → XML_INVALIDO
    def test_resposta_nao_json_retorna_xml_invalido(self):
        conector = _MockConectorADN([_MockResponse(200, '<html>erro</html>')])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()
        self.assertEqual(resultado, 'XML_INVALIDO')

    # 20. URL enviada ao ADN contem cnpjConsulta
    def test_url_contem_cnpj_consulta(self):
        conector = _MockConectorADN([_resp_vazia()])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        self.assertEqual(len(conector.urls_chamadas), 1)
        url = conector.urls_chamadas[0]
        self.assertIn('cnpjConsulta=12345678000199', url)
        self.assertIn('/DFe/', url)

    # 21. Homologacao usa endpoint correto
    def test_homologacao_usa_endpoint_correto(self):
        import os
        with patch.dict(os.environ, {'SEFAZ_HOMOLOGACAO': 'True'}):
            conector = _MockConectorADN([_resp_vazia()])
            svc = NFSeADNCapturaService(conector, self.cliente)
            svc.capturar_proximo_lote()
        self.assertIn('producaorestrita', conector.urls_chamadas[0])

    # 22. Producao usa endpoint correto
    def test_producao_usa_endpoint_correto(self):
        import os
        with patch.dict(os.environ, {'SEFAZ_HOMOLOGACAO': 'False'}):
            conector = _MockConectorADN([_resp_vazia()])
            svc = NFSeADNCapturaService(conector, self.cliente)
            svc.capturar_proximo_lote()
        self.assertIn('adn.nfse.gov.br', conector.urls_chamadas[0])
        self.assertNotIn('producaorestrita', conector.urls_chamadas[0])

    # 23. Extracao de valor do XML
    def test_extrai_valor_do_xml(self):
        xml_str = (
            '<nfse>'
            '<xNome>Prestadora XYZ</xNome>'
            '<vServicos>2750.50</vServicos>'
            '</nfse>'
        )
        conector = _MockConectorADN([
            _resp_ok([_item(1, CHAVE_1, xml_str=xml_str)], ult_nsu=1, max_nsu=1)
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        svc.capturar_proximo_lote()

        doc = Documento.objects.get(chave=CHAVE_1)
        self.assertAlmostEqual(float(doc.valor), 2750.50, places=2)
        self.assertEqual(doc.emitente, 'Prestadora XYZ')

    # 24. XML malformado: documento e salvo com defaults, nao levanta excecao
    def test_xml_malformado_usa_defaults_sem_levantar_excecao(self):
        conector = _MockConectorADN([
            _resp_ok(
                [_item(1, CHAVE_1, xml_str='<<xml invalido>>')],
                ult_nsu=1, max_nsu=1
            )
        ])
        svc = NFSeADNCapturaService(conector, self.cliente)
        resultado = svc.capturar_proximo_lote()

        self.assertIn(resultado, ('FINALIZADO', 'TEM_MAIS_DADOS'))
        doc = Documento.objects.get(chave=CHAVE_1)
        self.assertEqual(doc.emitente, 'EMITENTE NFS-e')

    # 25. capturar_por_chave_direta retorna SUCESSO se chave ja esta no banco
    def test_busca_direta_sucesso_chave_ja_existe(self):
        Documento.objects.create(
            cliente=self.cliente,
            chave=CHAVE_1,
            tipo_documento='NFSE',
            emitente='Prestadora',
            valor=100,
            data_emissao='2026-01-01',
            competencia='2026-01',
            status='COMPLETO',
        )
        svc = NFSeADNCapturaService(_MockConectorADN([]), self.cliente)
        resultado = svc.capturar_por_chave_direta(CHAVE_1)
        self.assertEqual(resultado, 'SUCESSO')

    # 26. capturar_por_chave_direta retorna NOTA_NAO_ENCONTRADA se fila vazia
    def test_busca_direta_nota_nao_encontrada(self):
        respostas = [_resp_vazia() for _ in range(10)]
        svc = NFSeADNCapturaService(_MockConectorADN(respostas), self.cliente)
        resultado = svc.capturar_por_chave_direta(CHAVE_1)
        self.assertEqual(resultado, 'NOTA_NAO_ENCONTRADA')
