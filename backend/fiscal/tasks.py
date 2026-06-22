import logging
import os

from celery import group, shared_task
from django.utils import timezone

from fiscal.conectores.cte import CTeCapturaService
from fiscal.conectores.fabrica import inicializar_cliente_sefaz
from fiscal.conectores.nfe import NFeCapturaService
from fiscal.conectores.nfse import NFSeADNCapturaService
from fiscal.models import Cliente, LogCaptura
from fiscal.services.cofre import decrypt_a1

logger = logging.getLogger(__name__)

_HOMOLOGACAO = os.environ.get('SEFAZ_HOMOLOGACAO', 'True') != 'False'


def _capturar_sentry(exc, contexto: dict):
    """Envia exceção ao Sentry com contexto fiscal estruturado, se configurado."""
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_context('fiscal', contexto)
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass  # Sentry não configurado ou indisponível — nunca bloqueia a captura


def _esgotar_fila(service, cliente, tipo_doc: str) -> str:
    """
    Loop incremental de NSU sem teto artificial.
    Para apenas quando o ADN confirma fila vazia (lote vazio ou ultNSU >= maxNSU).
    """
    resultado = 'ERRO_CONEXAO'
    lote = 0
    while True:
        resultado = service.capturar_proximo_lote()
        lote += 1
        logger.info('[%s] %s lote %d: %s', tipo_doc, cliente.razao_social, lote, resultado)
        if resultado != 'TEM_MAIS_DADOS':
            break
    return resultado


def capturar_cliente(cliente) -> dict:
    """
    Executa captura NF-e + CT-e + NFS-e para um unico cliente.
    Chamado pelo endpoint manual (views.py) e pelo worker Beat.
    Retorna {'sucesso': bool, 'mensagem': str}.
    """
    logger.info('Processando: %s (%s)', cliente.razao_social, cliente.cnpj)

    cert_db = cliente.certificados.filter(ativo=True).first()
    if not cert_db:
        msg = 'Sem certificado ativo.'
        logger.warning('%s: %s', cliente.razao_social, msg)
        return {'sucesso': False, 'mensagem': msg}

    if not cert_db.conteudo_criptografado or not cert_db.senha_criptografada:
        msg = 'Conteudo ou senha do certificado ausente no cofre.'
        logger.error('%s: %s', cliente.razao_social, msg)
        return {'sucesso': False, 'mensagem': msg}

    sucesso  = True
    mensagem = ''
    erros    = []

    try:
        senha    = decrypt_a1(bytes(cert_db.senha_criptografada)).decode('utf-8')
        conector = inicializar_cliente_sefaz(
            cliente_obj=cliente,
            senha_certificado=senha,
            homologacao=_HOMOLOGACAO,
        )

        # NF-e (SOAP distNSU)
        nfe_service = NFeCapturaService(conector_sefaz=conector, cliente=cliente)
        res_nfe = _esgotar_fila(nfe_service, cliente, 'NFE')
        if res_nfe in ('ERRO_CONEXAO', 'ERRO_HTTP'):
            erros.append(f'NF-e: {res_nfe}')

        # CT-e (SOAP distNSU)
        cte_service = CTeCapturaService(conector_sefaz=conector, cliente=cliente)
        res_cte = _esgotar_fila(cte_service, cliente, 'CTE')
        if res_cte in ('ERRO_CONEXAO', 'ERRO_HTTP'):
            erros.append(f'CT-e: {res_cte}')

        # NAO_IMPLEMENTADO nao e erro -- SOAP pendente, nao bloqueia NFS-e

        # NFS-e (REST ADN)
        nfse_service = NFSeADNCapturaService(conector_sefaz=conector, cliente=cliente)
        res_nfse = _esgotar_fila(nfse_service, cliente, 'NFSE')
        if res_nfse in ('ERRO_CONEXAO', 'ERRO_HTTP'):
            erros.append(f'NFS-e: {res_nfse}')

        if erros:
            sucesso  = False
            mensagem = 'Erros parciais: ' + '; '.join(erros)
        else:
            partes = []
            if res_nfe  not in ('NAO_IMPLEMENTADO',): partes.append(f'NF-e ({res_nfe})')
            if res_cte  not in ('NAO_IMPLEMENTADO',): partes.append(f'CT-e ({res_cte})')
            if res_nfse not in ('NAO_IMPLEMENTADO',): partes.append(f'NFS-e ({res_nfse})')
            mensagem = 'Captura ' + ' + '.join(partes) + ' concluida.' if partes else 'Nenhum conector ativo.'

    except Exception as e:
        sucesso  = False
        mensagem = str(e)
        logger.error(
            '[CAPTURA-001] Falha critica cliente=%s cnpj=%s erro=%s',
            cliente.razao_social, cliente.cnpj, mensagem,
        )
        _capturar_sentry(e, {'cliente_id': cliente.pk, 'cnpj': cliente.cnpj, 'etapa': 'captura_geral'})

    LogCaptura.objects.create(
        cliente=cliente,
        tipo_documento='NFE+CTE+NFSE',
        sucesso=sucesso,
        mensagem=mensagem,
    )
    return {'sucesso': sucesso, 'mensagem': mensagem}


@shared_task(
    bind=True,
    name='fiscal.tasks.capturar_cliente_task',
    max_retries=3,
    # Backoff exponencial: 1min, 2min, 4min — evita hammering na SEFAZ
    default_retry_delay=60,
    rate_limit='10/m',  # máx 10 clientes/min por worker — respeita limite da SEFAZ
    queue='captura',
    acks_late=True,  # recoloca na fila se o worker cair mid-task
)
def capturar_cliente_task(self, cliente_id: int) -> dict:
    """Task isolada por cliente — permite execução paralela via Celery group."""
    try:
        cliente = Cliente.objects.get(pk=cliente_id)
        return capturar_cliente(cliente)
    except Cliente.DoesNotExist:
        logger.error('[CAPTURA-002] cliente_id=%s não encontrado na base.', cliente_id)
        return {'sucesso': False, 'mensagem': 'Cliente não encontrado.'}
    except Exception as exc:
        tentativa = self.request.retries + 1
        countdown = 60 * (2 ** self.request.retries)  # 60s, 120s, 240s
        logger.warning(
            '[CAPTURA-003] cliente_id=%s tentativa=%d/%d erro=%s retry_em=%ds',
            cliente_id, tentativa, self.max_retries + 1, exc, countdown,
        )
        _capturar_sentry(exc, {
            'cliente_id': cliente_id,
            'tentativa': tentativa,
            'etapa': 'capturar_cliente_task',
        })
        raise self.retry(exc=exc, countdown=countdown)


@shared_task(name='fiscal.tasks.executar_recolhimento_lote_nsu')
def executar_recolhimento_lote_nsu():
    """
    Task master periódica (Beat: 4h).
    Dispara captura NF-e + CT-e + NFS-e em paralelo para todos os clientes ativos.
    Cada cliente roda numa task Celery independente — o ciclo completo leva
    max(latência_cliente) em vez de sum(latência_cliente).
    """
    logger.info('==> Iniciando ciclo de captura paralela por NSU: %s', timezone.now())
    ids = list(Cliente.objects.filter(ativo=True).values_list('id', flat=True))
    if not ids:
        logger.info('==> Nenhum cliente ativo — ciclo ignorado.')
        return 'Nenhum cliente ativo.'

    job = group(capturar_cliente_task.s(cid) for cid in ids)
    job.delay()

    logger.info('==> %d task(s) de captura disparadas em paralelo.', len(ids))
    return f'{len(ids)} cliente(s) disparado(s) em paralelo.'
