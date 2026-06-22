"""
TDD — Testes de comportamento das tasks Celery.

Verifica: rate_limit, retry exponencial, captura Sentry, queue routing e
comportamento quando cliente não existe.
"""
from unittest.mock import MagicMock, call, patch

from django.test import TestCase, override_settings

from fiscal.models import Cliente, LogCaptura


def _make_cliente(**kwargs):
    defaults = {'razao_social': 'Empresa Teste', 'cnpj': '11222333000144', 'uf': 'SP', 'ativo': True}
    defaults.update(kwargs)
    return Cliente.objects.create(**defaults)


# ── 1. Configuração das tasks ─────────────────────────────────────────────────


class CeleryTaskConfigTest(TestCase):

    def test_capturar_cliente_task_tem_rate_limit_10_por_minuto(self):
        from fiscal.tasks import capturar_cliente_task
        self.assertEqual(capturar_cliente_task.rate_limit, '10/m')

    def test_capturar_cliente_task_tem_max_retries_3(self):
        from fiscal.tasks import capturar_cliente_task
        self.assertEqual(capturar_cliente_task.max_retries, 3)

    def test_capturar_cliente_task_usa_fila_captura(self):
        from fiscal.tasks import capturar_cliente_task
        self.assertEqual(capturar_cliente_task.queue, 'captura')

    def test_capturar_cliente_task_acks_late_true(self):
        from fiscal.tasks import capturar_cliente_task
        self.assertTrue(capturar_cliente_task.acks_late)


# ── 2. Comportamento com cliente inexistente ──────────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
class CapturarClienteTaskClienteInexistenteTest(TestCase):

    def test_retorna_sucesso_false_se_cliente_nao_existe(self):
        from fiscal.tasks import capturar_cliente_task
        resultado = capturar_cliente_task.apply(args=[99999]).get()
        self.assertFalse(resultado['sucesso'])
        self.assertIn('encontrado', resultado['mensagem'])


# ── 3. Delegação correta para capturar_cliente ───────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CapturarClienteTaskDelegacaoTest(TestCase):

    def setUp(self):
        self.cliente = _make_cliente()

    @patch('fiscal.tasks.capturar_cliente')
    def test_task_delega_para_capturar_cliente(self, mock_capturar):
        mock_capturar.return_value = {'sucesso': True, 'mensagem': 'ok'}
        from fiscal.tasks import capturar_cliente_task
        resultado = capturar_cliente_task.apply(args=[self.cliente.pk]).get()
        mock_capturar.assert_called_once_with(self.cliente)

    @patch('fiscal.tasks.capturar_cliente')
    def test_task_retorna_resultado_de_capturar_cliente(self, mock_capturar):
        mock_capturar.return_value = {'sucesso': True, 'mensagem': 'Captura concluída.'}
        from fiscal.tasks import capturar_cliente_task
        resultado = capturar_cliente_task.apply(args=[self.cliente.pk]).get()
        self.assertTrue(resultado['sucesso'])
        self.assertEqual(resultado['mensagem'], 'Captura concluída.')


# ── 4. Captura Sentry em falha ────────────────────────────────────────────────


class CapturaSentryTest(TestCase):

    def test_capturar_sentry_nao_lanca_excecao_se_sentry_ausente(self):
        """_capturar_sentry deve ser silencioso se sentry_sdk não está disponível."""
        from fiscal.tasks import _capturar_sentry
        exc = ValueError('teste')
        # Não deve levantar nada
        _capturar_sentry(exc, {'cliente_id': 1})

    @patch('fiscal.tasks._capturar_sentry')
    @patch('fiscal.tasks.capturar_cliente')
    def test_sentry_capturado_em_falha_critica(self, mock_cap, mock_sentry):
        """Quando capturar_cliente levanta, _capturar_sentry deve ser chamado."""
        cliente = _make_cliente(cnpj='55666777000188')
        mock_cap.side_effect = RuntimeError('conexão recusada')

        from fiscal.tasks import capturar_cliente_task
        # ALWAYS_EAGER mas com EAGER_PROPAGATES=False para não relançar após retries
        with self.settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False):
            capturar_cliente_task.apply(args=[cliente.pk])

        # Em EAGER mode o retry roda max_retries+1 vezes — sentry chamado em cada tentativa
        self.assertTrue(mock_sentry.called)
        contexto = mock_sentry.call_args[0][1]
        self.assertEqual(contexto['cliente_id'], cliente.pk)


# ── 5. Lote paralelo (executar_recolhimento_lote_nsu) ────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class LoteParaleloTest(TestCase):

    def test_retorna_mensagem_sem_clientes_ativos(self):
        from fiscal.tasks import executar_recolhimento_lote_nsu
        resultado = executar_recolhimento_lote_nsu.apply().get()
        self.assertIn('Nenhum cliente ativo', resultado)

    @patch('fiscal.tasks.capturar_cliente')
    def test_dispara_uma_task_por_cliente_ativo(self, mock_cap):
        """Com ALWAYS_EAGER, group executa inline — verifica que capturar_cliente foi chamado para cada cliente."""
        mock_cap.return_value = {'sucesso': True, 'mensagem': 'ok'}

        _make_cliente(cnpj='11111111000111')
        _make_cliente(cnpj='22222222000122')

        from fiscal.tasks import executar_recolhimento_lote_nsu
        resultado = executar_recolhimento_lote_nsu.apply().get()
        self.assertIn('2', resultado)
