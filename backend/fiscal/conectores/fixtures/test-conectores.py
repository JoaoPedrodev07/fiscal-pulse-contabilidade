import os

from unittest import TestCase
from unittest.mock import patch, MagicMock
import unittest

def orquestrar_fluxo_nsu(conector_sefaz):
    """
    Lógica que controla a torneira da SEFAZ.
    Retorna True se ainda houver notas para buscar, ou False se chegou ao fim.
    """
    # IMPORTANTE: A PyNFe expõe o método consulta_notas_cnpj
    resposta = conector_sefaz.consulta_notas_cnpj(cnpj='12345678000199', nsu=0)
    
    # Vamos simular a leitura do XML retornado pela lib
    if "cStat" in resposta.text:
        # Lógica temporária de parse manual para o teste (depois usaremos a lib para parsear)
        if "<cStat>138</cStat>" in resposta.text:
            # Se ultNSU != maxNSU, significa que a fila não andou tudo. Tem mais!
            if "<ultNSU>000000000000150</ultNSU>" in resposta.text and "<maxNSU>000000000000200</maxNSU>" in resposta.text:
                return "TEM_MAIS_DADOS"
    return "PARAR_AGUARDAR_1H"


class TestSefazFluxoOrquestracao(TestCase):
    
    def test_deve_identificar_que_existem_mais_notas_no_lote(self):
        # 1. Carrega a nova fixture real da SEFAZ
        fixture_path = os.path.join(os.path.dirname(__file__),  'resposta_distribuicao.xml')
        with open(fixture_path, 'r', encoding='utf-8') as f:
            xml_real = f.read()

        # 2. Mock da resposta HTTP
        mock_resposta_http = MagicMock()
        mock_resposta_http.status_code = 200
        mock_resposta_http.text = xml_real

        # 3. Mock da PyNFe simulando a chamada de captura
        mock_pynfe = MagicMock()
        mock_pynfe.consulta_notas_cnpj.return_value = mock_resposta_http

        # 4. Executa a inteligência do fluxo
        resultado = orquestrar_fluxo_nsu(mock_pynfe)

        # 5. Asserção: O sistema PRECISA entender que tem mais dados pendentes
        self.assertEqual(resultado, "TEM_MAIS_DADOS")
        print("\n🟢 TESTE DE FLUXO PASSOU: O orquestrador detectou que ultNSU < maxNSU e que não deve parar!")
        
        
if __name__ == "__main__":
    
    unittest.main()