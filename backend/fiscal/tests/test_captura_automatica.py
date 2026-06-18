"""
Testes do fluxo de captura automática sem senha manual.

Proposta de valor central: o contador NÃO digita senha.
O sistema usa o A1 do cofre AES, chama NF-e + CT-e + NFS-e em sequência
e registra o resultado em LogCaptura.

Invariantes verificadas:
  1. Sem certificado ativo → retorna erro sem crashar
  2. Sem conteúdo no cofre → retorna erro sem crashar
  3. Fluxo completo OK → sucesso nos 3 tipos, LogCaptura criado
  4. Falha parcial (NF-e falha, CT-e e NFS-e OK) → sucesso=False, erros listados
  5. Exceção inesperada na inicialização do conector → captura o erro e loga
  6. Worker Beat chama capturar_cliente para cada cliente ativo
  7. Clientes inativos NÃO são processados pelo Beat
  8. Mensagem de sucesso menciona os 3 tipos de documento

NUNCA usa cofre real nem chama SEFAZ — tudo mockado.
A senha não aparece em nenhum assert — é usada internamente e descartada.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from fiscal.models import Cliente, Certificado, LogCaptura
from fiscal.tasks import capturar_cliente, executar_recolhimento_lote_nsu


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENHA_FAKE = b'senha-super-secreta'
_CONTEUDO_FAKE = b'pfx-binario-fake'


def _make_cliente(ativo=True, cnpj='54565144000114'):
    return Cliente.objects.create(
        cnpj=cnpj,
        razao_social='BotoDerma Oficial LTDA',
        uf='RJ',
        ativo=ativo,
    )


def _add_cert(cliente, com_conteudo=True):
    """Cria certificado com ou sem conteúdo no cofre."""
    cert = Certificado(
        cliente=cliente,
        nome_arquivo='BotoDerma.pfx',
        validade='2027-03-12',
        ativo=True,
    )
    if com_conteudo:
        cert.conteudo_criptografado = _CONTEUDO_FAKE
        cert.senha_criptografada = _SENHA_FAKE
    cert.save()
    return cert


def _patch_cofre():
    """Mocka decrypt_a1 para retornar senha sem chamar o Fernet real."""
    return patch('fiscal.tasks.decrypt_a1', return_value=b'senha-decifrada')


def _patch_conector():
    """Mocka inicializar_cliente_sefaz retornando um objeto fake."""
    return patch('fiscal.tasks.inicializar_cliente_sefaz', return_value=MagicMock())


def _mock_service_ok():
    """Serviço que sempre retorna FINALIZADO."""
    svc = MagicMock()
    svc.capturar_proximo_lote.return_value = 'FINALIZADO'
    return svc


def _mock_service_erro():
    """Serviço que sempre retorna ERRO_CONEXAO."""
    svc = MagicMock()
    svc.capturar_proximo_lote.return_value = 'ERRO_CONEXAO'
    return svc


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

class TestCapturaAutomaticaSemSenha(TestCase):

    def setUp(self):
        self.cliente = _make_cliente()

    # 1. Sem certificado ativo → erro sem crash
    def test_sem_certificado_retorna_erro(self):
        resultado = capturar_cliente(self.cliente)
        self.assertFalse(resultado['sucesso'])
        self.assertIn('certificado', resultado['mensagem'].lower())

    # 2. Certificado sem conteúdo no cofre → erro sem crash
    def test_sem_conteudo_cofre_retorna_erro(self):
        _add_cert(self.cliente, com_conteudo=False)
        resultado = capturar_cliente(self.cliente)
        self.assertFalse(resultado['sucesso'])

    # 3. Fluxo completo OK — sem senha manual, 3 tipos capturados
    def test_fluxo_completo_sucesso_sem_senha_manual(self):
        _add_cert(self.cliente)

        with _patch_cofre(), _patch_conector(), \
             patch('fiscal.tasks.NFeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.CTeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.NFSeADNCapturaService', return_value=_mock_service_ok()):

            resultado = capturar_cliente(self.cliente)

        self.assertTrue(resultado['sucesso'])

    # 4. Sucesso não exige senha no resultado — a senha é interna ao cofre
    def test_resultado_nao_expoe_senha(self):
        _add_cert(self.cliente)

        with _patch_cofre(), _patch_conector(), \
             patch('fiscal.tasks.NFeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.CTeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.NFSeADNCapturaService', return_value=_mock_service_ok()):

            resultado = capturar_cliente(self.cliente)

        resultado_str = str(resultado)
        self.assertNotIn('senha', resultado_str.lower())
        self.assertNotIn('password', resultado_str.lower())

    # 5. LogCaptura criado após execução
    def test_log_captura_criado(self):
        _add_cert(self.cliente)

        with _patch_cofre(), _patch_conector(), \
             patch('fiscal.tasks.NFeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.CTeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.NFSeADNCapturaService', return_value=_mock_service_ok()):

            capturar_cliente(self.cliente)

        self.assertEqual(LogCaptura.objects.filter(cliente=self.cliente).count(), 1)
        log = LogCaptura.objects.get(cliente=self.cliente)
        self.assertTrue(log.sucesso)

    # 6. Falha parcial (NF-e erro, CT-e e NFS-e OK) → sucesso=False, erros listados
    def test_falha_parcial_nfe_reporta_erro_parcial(self):
        _add_cert(self.cliente)

        with _patch_cofre(), _patch_conector(), \
             patch('fiscal.tasks.NFeCapturaService', return_value=_mock_service_erro()), \
             patch('fiscal.tasks.CTeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.NFSeADNCapturaService', return_value=_mock_service_ok()):

            resultado = capturar_cliente(self.cliente)

        self.assertFalse(resultado['sucesso'])
        self.assertIn('NF-e', resultado['mensagem'])

    # 7. Falha de todos os 3 → sucesso=False, todos listados
    def test_falha_total_lista_todos_os_erros(self):
        _add_cert(self.cliente)

        with _patch_cofre(), _patch_conector(), \
             patch('fiscal.tasks.NFeCapturaService', return_value=_mock_service_erro()), \
             patch('fiscal.tasks.CTeCapturaService', return_value=_mock_service_erro()), \
             patch('fiscal.tasks.NFSeADNCapturaService', return_value=_mock_service_erro()):

            resultado = capturar_cliente(self.cliente)

        self.assertFalse(resultado['sucesso'])
        self.assertIn('NF-e', resultado['mensagem'])
        self.assertIn('CT-e', resultado['mensagem'])
        self.assertIn('NFS-e', resultado['mensagem'])

    # 8. Exceção no inicializar_cliente_sefaz → captura erro e loga
    def test_excecao_na_inicializacao_do_conector_e_capturada(self):
        _add_cert(self.cliente)

        with _patch_cofre(), \
             patch('fiscal.tasks.inicializar_cliente_sefaz', side_effect=RuntimeError('mTLS falhou')):

            resultado = capturar_cliente(self.cliente)

        self.assertFalse(resultado['sucesso'])
        self.assertIn('mTLS', resultado['mensagem'])
        self.assertEqual(LogCaptura.objects.filter(cliente=self.cliente, sucesso=False).count(), 1)

    # 9. Mensagem de sucesso menciona NFS-e (confirmação de que NFS-e é automática)
    def test_mensagem_sucesso_menciona_nfse(self):
        _add_cert(self.cliente)

        with _patch_cofre(), _patch_conector(), \
             patch('fiscal.tasks.NFeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.CTeCapturaService', return_value=_mock_service_ok()), \
             patch('fiscal.tasks.NFSeADNCapturaService', return_value=_mock_service_ok()):

            resultado = capturar_cliente(self.cliente)

        self.assertIn('NFS-e', resultado['mensagem'])


class TestBeatProcessaClientesAtivos(TestCase):
    """Garante que o worker Beat só processa clientes ativos."""

    # 10. Beat chama capturar_cliente para cada cliente ativo
    def test_beat_processa_clientes_ativos(self):
        c1 = _make_cliente(ativo=True, cnpj='11111111000101')
        c2 = _make_cliente(ativo=True, cnpj='22222222000102')

        with patch('fiscal.tasks.capturar_cliente') as mock_captura:
            mock_captura.return_value = {'sucesso': True, 'mensagem': 'ok'}
            executar_recolhimento_lote_nsu()

        cnpjs_processados = {call.args[0].cnpj for call in mock_captura.call_args_list}
        self.assertIn(c1.cnpj, cnpjs_processados)
        self.assertIn(c2.cnpj, cnpjs_processados)

    # 11. Beat NÃO processa clientes inativos
    def test_beat_ignora_clientes_inativos(self):
        ativo   = _make_cliente(ativo=True,  cnpj='33333333000103')
        inativo = _make_cliente(ativo=False, cnpj='44444444000104')

        with patch('fiscal.tasks.capturar_cliente') as mock_captura:
            mock_captura.return_value = {'sucesso': True, 'mensagem': 'ok'}
            executar_recolhimento_lote_nsu()

        cnpjs_processados = {call.args[0].cnpj for call in mock_captura.call_args_list}
        self.assertIn(ativo.cnpj, cnpjs_processados)
        self.assertNotIn(inativo.cnpj, cnpjs_processados)

    # 12. Beat sem nenhum cliente ativo → não crasha
    def test_beat_sem_clientes_ativos_nao_crasha(self):
        _make_cliente(ativo=False, cnpj='55555555000105')

        with patch('fiscal.tasks.capturar_cliente') as mock_captura:
            resultado = executar_recolhimento_lote_nsu()

        mock_captura.assert_not_called()
        self.assertIn('0', resultado)
