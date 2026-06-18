import logging
import os

from celery import shared_task
from django.utils import timezone

from fiscal.conectores.cte import CTeCapturaService
from fiscal.conectores.fabrica import inicializar_cliente_sefaz
from fiscal.conectores.nfe import NFeCapturaService
from fiscal.models import Cliente, LogCaptura
from fiscal.services.cofre import decrypt_a1

logger = logging.getLogger(__name__)

_MAX_LOTES_POR_CLIENTE = 5
_HOMOLOGACAO = os.environ.get('SEFAZ_HOMOLOGACAO', 'True') != 'False'


def _esgotar_fila(service, cliente, tipo_doc: str) -> str:
    """Loop incremental de NSU — para quando a fila esvazia ou atinge o teto."""
    resultado = 'ERRO_CONEXAO'
    for tentativa in range(_MAX_LOTES_POR_CLIENTE):
        resultado = service.capturar_proximo_lote()
        logger.info(f'[{tipo_doc}] {cliente.razao_social} lote {tentativa + 1}: {resultado}')
        if resultado != 'TEM_MAIS_DADOS':
            break
    return resultado


def capturar_cliente(cliente) -> dict:
    """
    Executa captura NF-e + CT-e para um único cliente.
    Chamado pelo endpoint manual (views.py) e pelo worker Beat.
    Retorna {'sucesso': bool, 'mensagem': str}.
    """
    logger.info(f'Processando: {cliente.razao_social} ({cliente.cnpj})')

    cert_db = cliente.certificados.filter(ativo=True).first()
    if not cert_db:
        msg = 'Sem certificado ativo.'
        logger.warning(f'{cliente.razao_social}: {msg}')
        return {'sucesso': False, 'mensagem': msg}

    if not cert_db.conteudo_criptografado or not cert_db.senha_criptografada:
        msg = 'Conteúdo ou senha do certificado ausente no cofre.'
        logger.error(f'{cliente.razao_social}: {msg}')
        return {'sucesso': False, 'mensagem': msg}

    sucesso = True
    mensagem = ''

    try:
        senha = decrypt_a1(bytes(cert_db.senha_criptografada)).decode('utf-8')
        conector = inicializar_cliente_sefaz(
            cliente_obj=cliente,
            senha_certificado=senha,
            homologacao=_HOMOLOGACAO,
        )

        nfe_service = NFeCapturaService(conector_sefaz=conector, cliente=cliente)
        _esgotar_fila(nfe_service, cliente, 'NFE')

        cte_service = CTeCapturaService(conector_sefaz=conector, cliente=cliente)
        _esgotar_fila(cte_service, cliente, 'CTE')

        mensagem = 'Captura NF-e + CT-e concluída com sucesso.'

    except Exception as e:
        sucesso = False
        mensagem = str(e)
        logger.error(f'Falha crítica em {cliente.razao_social}: {mensagem}')

    LogCaptura.objects.create(
        cliente=cliente,
        tipo_documento='NFE+CTE',
        sucesso=sucesso,
        mensagem=mensagem,
    )
    return {'sucesso': sucesso, 'mensagem': mensagem}


@shared_task(name='fiscal.tasks.executar_recolhimento_lote_nsu')
def executar_recolhimento_lote_nsu():
    """Task master periódica (Beat: 4h). NF-e + CT-e para todos os clientes ativos."""
    logger.info(f'==> Iniciando ciclo de captura automática por NSU: {timezone.now()}')
    clientes_ativos = Cliente.objects.filter(ativo=True)
    total_processado = 0

    for cliente in clientes_ativos:
        capturar_cliente(cliente)
        total_processado += 1

    logger.info('==> Ciclo de captura automática por NSU finalizado.')
    return f'Rotina concluída. {total_processado} cliente(s) verificado(s).'
