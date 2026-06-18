import logging

from celery import shared_task
from django.utils import timezone

from fiscal.models import Cliente, Documento, LogCaptura, StatusDocumento
from fiscal.conectores.nfe import NFeCapturaService
from fiscal.conectores.cte import CTeCapturaService
from fiscal.conectores.nfse import NFSeADNCapturaService
from fiscal.conectores.manifestacao import manifestar_documento
from fiscal.conectores.fabrica import inicializar_cliente_sefaz
from fiscal.services.cofre import decrypt_a1

logger = logging.getLogger(__name__)

_MAX_LOTES_POR_CLIENTE = 5  # teto de segurança por cliente/tipo para evitar loops


def _esgotar_fila(service, cliente, tipo_doc: str):
    """Loop incremental de NSU — para quando a fila esvazia ou atinge o teto."""
    for tentativa in range(_MAX_LOTES_POR_CLIENTE):
        resultado = service.capturar_proximo_lote()
        logger.info(f"[{tipo_doc}] {cliente.razao_social} lote {tentativa + 1}: {resultado}")
        if resultado != 'TEM_MAIS_DADOS':
            break
    return resultado


def _manifestar_pendentes(conector, cliente):
    """
    Envia Ciência da Operação para todos os documentos NF-e com status CAPTURADO.
    Critério 2 do escopo: resumo → manifestação automática → XML completo armazenado.
    """
    pendentes = Documento.objects.filter(
        cliente=cliente,
        tipo_documento='NFE',
        status=StatusDocumento.CAPTURADO,
    ).select_related('cliente')

    total = 0
    for documento in pendentes:
        manifestar_documento(conector, documento)
        total += 1

    if total:
        logger.info(f"Manifestação: {total} documento(s) processados para {cliente.razao_social}.")


def capturar_cliente(cliente) -> dict:
    """
    Executa a captura completa para um único cliente.
    Chamado tanto pela task periódica quanto pelo endpoint manual.
    Retorna {'sucesso': bool, 'mensagem': str}.
    """
    logger.info(f'Processando: {cliente.razao_social} ({cliente.cnpj})')

    cert_db = cliente.certificados.filter(ativo=True).first()
    if not cert_db:
        msg = f'{cliente.razao_social}: sem certificado ativo.'
        logger.warning(msg)
        return {'sucesso': False, 'mensagem': msg}

    if not cert_db.senha_criptografada:
        msg = f'{cliente.razao_social}: senha do certificado ausente.'
        logger.error(msg)
        return {'sucesso': False, 'mensagem': msg}

    sucesso = True
    mensagem = ''

    try:
        senha = decrypt_a1(bytes(cert_db.senha_criptografada)).decode('utf-8')

        conector = inicializar_cliente_sefaz(
            cliente_obj=cliente,
            senha_certificado=senha,
            homologacao=True,  # NUNCA False sem decisão explícita de ir a produção
        )

        nfe_service = NFeCapturaService(conector_sefaz=conector, cliente=cliente)
        _esgotar_fila(nfe_service, cliente, 'NFE')

        _manifestar_pendentes(conector, cliente)

        cte_service = CTeCapturaService(conector_sefaz=conector, cliente=cliente)
        _esgotar_fila(cte_service, cliente, 'CTE')

        if cliente.uf.upper() in ('RJ',):
            nfse_service = NFSeADNCapturaService(conector_sefaz=conector, cliente=cliente)
            _esgotar_fila(nfse_service, cliente, 'NFSE')

        mensagem = 'Captura concluída com sucesso.'

    except Exception as e:
        sucesso = False
        mensagem = str(e)
        logger.error(f'Falha crítica em {cliente.razao_social}: {mensagem}')

    LogCaptura.objects.create(
        cliente=cliente,
        tipo_documento='NFE+CTE+NFSE',
        sucesso=sucesso,
        mensagem=mensagem,
    )
    return {'sucesso': sucesso, 'mensagem': mensagem}


@shared_task(name='fiscal.tasks.executar_captura_nfe_todos_clientes')
def executar_captura_nfe_todos_clientes():
    """Task master periódica (Beat: 4h). Itera sobre todos os clientes ativos."""
    logger.info('Iniciando rotina periódica de captura...')
    clientes_ativos = Cliente.objects.filter(ativo=True)
    total_processado = 0

    for cliente in clientes_ativos:
        capturar_cliente(cliente)
        total_processado += 1

    return f'Rotina concluída. {total_processado} cliente(s) verificado(s).'
