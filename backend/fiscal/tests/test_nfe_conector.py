"""
Teste de integração do NFeCapturaService com banco SQLite em memória.

Verifica que após uma resposta cStat=138:
  - ControleNSU.ultimo_nsu e max_nsu são persistidos corretamente
  - Documento e Xml são criados no banco
  - Idempotência: segunda chamada com mesma chave não duplica

A cobertura de invariantes NSU (cStat=137, UP_TO_DATE, erros) está em
test_nsu_logic.py. Este módulo foca na camada de persistência.
"""
import base64
import gzip
from unittest.mock import MagicMock

from django.test import TestCase

from fiscal.conectores.nfe import NFeCapturaService
from fiscal.models import Cliente, ControleNSU, Documento, Xml


def _gz64(xml_text: str) -> str:
    return base64.b64encode(gzip.compress(xml_text.encode('utf-8'))).decode('ascii')


def _nfe_proc(chave: str = '35260612345678000199550010000000010000000001') -> str:
    return (
        f'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">'
        f'<NFe><infNFe>'
        f'<emit><xNome>Fornecedor Teste LTDA</xNome></emit>'
        f'<total><ICMSTot><vNF>1500.00</vNF></ICMSTot></total>'
        f'</infNFe></NFe>'
        f'<protNFe><infProt><chNFe>{chave}</chNFe></infProt></protNFe>'
        f'</nfeProc>'
    )


def _envelope_138(ult_nsu: int, max_nsu: int, chave: str) -> str:
    doc_zip = _gz64(_nfe_proc(chave))
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">'
        '<tpAmb>2</tpAmb>'
        '<cStat>138</cStat>'
        '<xMotivo>Documentos localizados</xMotivo>'
        f'<ultNSU>{str(ult_nsu).zfill(15)}</ultNSU>'
        f'<maxNSU>{str(max_nsu).zfill(15)}</maxNSU>'
        f'<loteDistDFeInt>'
        f'<docZip NSU="{str(ult_nsu).zfill(15)}" schema="procNFe">{doc_zip}</docZip>'
        f'</loteDistDFeInt>'
        '</retDistDFeInt>'
    )


class TestNFeCapturaPersistencia(TestCase):

    def setUp(self):
        self.cliente = Cliente.objects.create(
            razao_social='Empresa Teste LTDA',
            cnpj='12345678000199',
            uf='SP',
        )

    def _mock_conector(self, xml_text: str) -> MagicMock:
        resposta = MagicMock()
        resposta.status_code = 200
        resposta.text = xml_text
        conector = MagicMock()
        conector.consulta_notas_cnpj.return_value = resposta
        return conector

    def test_persiste_nsu_apos_resposta_138(self):
        chave = '35260612345678000199550010000000010000000001'
        xml = _envelope_138(ult_nsu=150, max_nsu=200, chave=chave)
        service = NFeCapturaService(
            conector_sefaz=self._mock_conector(xml),
            cliente=self.cliente,
        )

        resultado = service.capturar_proximo_lote()

        self.assertEqual(resultado, 'TEM_MAIS_DADOS')
        ctrl = ControleNSU.objects.get(cliente=self.cliente)
        self.assertEqual(ctrl.ultimo_nsu, 150)
        self.assertEqual(ctrl.max_nsu, 200)

    def test_persiste_documento_e_xml_no_banco(self):
        chave = '35260612345678000199550010000000010000000002'
        xml = _envelope_138(ult_nsu=50, max_nsu=50, chave=chave)
        service = NFeCapturaService(
            conector_sefaz=self._mock_conector(xml),
            cliente=self.cliente,
        )

        service.capturar_proximo_lote()

        self.assertEqual(Documento.objects.filter(cliente=self.cliente).count(), 1)
        self.assertEqual(Xml.objects.filter(documento__cliente=self.cliente).count(), 1)

    def test_idempotencia_segunda_chamada_nao_duplica(self):
        chave = '35260612345678000199550010000000010000000003'
        xml = _envelope_138(ult_nsu=50, max_nsu=100, chave=chave)
        conector = self._mock_conector(xml)
        service = NFeCapturaService(conector_sefaz=conector, cliente=self.cliente)

        service.capturar_proximo_lote()
        # Reseta NSU para forçar re-consulta com o mesmo docZip
        ControleNSU.objects.filter(cliente=self.cliente, tipo_documento='NFE').update(
            ultimo_nsu=0, max_nsu=0,
        )
        service.capturar_proximo_lote()

        self.assertEqual(
            Documento.objects.filter(cliente=self.cliente, chave=chave).count(),
            1,
            'Idempotência violada: documento duplicado',
        )
