"""
Teste de integração para NFeCapturaService — versão standalone convertida
para Django TestCase. A cobertura completa está em fiscal/tests/test_nsu_logic.py
e fiscal/tests/test_nfe_conector.py.
"""
import base64
import gzip
from unittest.mock import MagicMock

from django.test import TestCase

from fiscal.conectores.nfe import NFeCapturaService
from fiscal.models import Cliente, ControleNSU, Documento, Xml


def _gz64(xml_text: str) -> str:
    return base64.b64encode(gzip.compress(xml_text.encode('utf-8'))).decode('ascii')


class TestNFeCapturaPersistenciaStandalone(TestCase):

    def setUp(self):
        self.cliente = Cliente.objects.create(
            razao_social='Empresa Teste LTDA',
            cnpj='12345678000199',
            uf='SP',
        )
        chave = '35260612345678000199550010000000010000000001'
        inner = (
            f'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">'
            f'<NFe><infNFe>'
            f'<emit><xNome>Fornecedor Teste</xNome></emit>'
            f'<total><ICMSTot><vNF>1000.00</vNF></ICMSTot></total>'
            f'</infNFe></NFe>'
            f'<protNFe><infProt><chNFe>{chave}</chNFe></infProt></protNFe>'
            f'</nfeProc>'
        )
        doc_zip = _gz64(inner)
        self.xml_sefaz = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">'
            '<tpAmb>2</tpAmb><cStat>138</cStat>'
            '<xMotivo>Documentos localizados</xMotivo>'
            '<ultNSU>000000000000150</ultNSU>'
            '<maxNSU>000000000000200</maxNSU>'
            f'<loteDistDFeInt>'
            f'<docZip NSU="000000000000150" schema="procNFe">{doc_zip}</docZip>'
            f'</loteDistDFeInt>'
            '</retDistDFeInt>'
        )

    def test_deve_atualizar_ponteiros_nsu_no_banco_apos_retorno_sefaz(self):
        mock_resposta = MagicMock()
        mock_resposta.status_code = 200
        mock_resposta.text = self.xml_sefaz

        mock_pynfe = MagicMock()
        mock_pynfe.consulta_notas_cnpj.return_value = mock_resposta

        service = NFeCapturaService(conector_sefaz=mock_pynfe, cliente=self.cliente)
        resultado = service.capturar_proximo_lote()

        self.assertEqual(resultado, 'TEM_MAIS_DADOS')

        ctrl = ControleNSU.objects.get(cliente=self.cliente)
        self.assertEqual(ctrl.ultimo_nsu, 150)
        self.assertEqual(ctrl.max_nsu, 200)

        total_docs = Documento.objects.filter(cliente=self.cliente).count()
        total_xmls = Xml.objects.filter(documento__cliente=self.cliente).count()
        self.assertGreater(total_docs, 0)
        self.assertEqual(total_docs, total_xmls)
