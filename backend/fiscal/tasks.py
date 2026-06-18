import logging
import os

from celery import shared_task
from django.utils import timezone

from fiscal.conectores.cte import CTeCapturaService
from fiscal.conectores.fabrica import inicializar_cliente_sefaz
from fiscal.conectores.nfe import NFeCapturaService
from fiscal.conectores.nfse import NFSeADNCapturaService
from fiscal.models import Cliente, LogCaptura
from fiscal.services.cofre import decrypt_a1

logger = logging.getLogger(__name__)

_MAX_LOTES_POR_CLIENTE = 5
_HOMOLOGACAO = os.environ.get('SEFAZ_HOMOLOGACAO', 'True') != 'False'


def _esgotar_fila(service, cliente, tipo_doc: str) -> str:
    """Loop incremental de NSU -- para quando a fila esvazia ou atinge o teto."""
    resultado = 'ERRO_CONEXAO'
    for tentativa in range(_MAX_LOTES_POR_CLIENTE):
        resultado = service.capturar_proximo_lote()
        logger.info('[%s] %s lote %d: %s', tipo_doc, cliente.razao_social, tentativa + 1, resultado)
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

        # NFS-e (REST ADN)
        nfse_service = NFSeADNCapturaService(conector_sefaz=conector, cliente=cliente)
        res_nfse = _esgotar_fila(nfse_service, cliente, 'NFSE')
        if res_nfse in ('ERRO_CONEXAO', 'ERRO_HTTP'):
            erros.append(f'NFS-e: {res_nfse}')

        if erros:
            sucesso  = False
            mensagem = 'Erros parciais: ' + '; '.join(erros)
        else:
            mensagem = f'Captura NF-e ({res_nfe}) + CT-e ({res_cte}) + NFS-e ({res_nfse}) concluida.'

    except Exception as e:
        sucesso  = False
        mensagem = str(e)
        logger.error('Falha critica em %s: %s', cliente.razao_social, mensagem)

    LogCaptura.objects.create(
        cliente=cliente,
        tipo_documento='NFE+CTE+NFSE',
        sucesso=sucesso,
        mensagem=mensagem,
    )
    return {'sucesso': sucesso, 'mensagem': mensagem}


@shared_task(name='fiscal.tasks.executar_recolhimento_lote_nsu')
def executar_recolhimento_lote_nsu():
    """Task master periodica (Beat: 4h). NF-e + CT-e + NFS-e para todos os clientes ativos."""
    logger.info('==> Iniciando ciclo de captura automatica por NSU: %s', timezone.now())
    clientes_ativos = Cliente.objects.filter(ativo=True)
    total = 0

    for cliente in clientes_ativos:
        capturar_cliente(cliente)
        total += 1

    logger.info('==> Ciclo de captura automatica por NSU finalizado.')
    return f'Rotina concluida. {total} cliente(s) verificado(s).'
