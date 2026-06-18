"""
Tarefas agendadas via Celery Beat para captura automática de documentos fiscais.
"""
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

_MAX_LOTES_POR_CLIENTE = 20  # Teto de segurança por cliente/tipo para evitar loops infinitos


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
    Executa a captura completa para um único cliente de forma isolada e resiliente.
    """
    logger.info(f'Processando: {cliente.razao_social} ({cliente.cnpj})')

    cert_db = cliente.certificados.filter(ativo=True).first()
    if not cert_db:
        msg = f'{cliente.razao_social}: sem certificado ativo.'
        logger.warning(msg)
        LogCaptura.objects.create(cliente=cliente, tipo_documento='TODOS', sucesso=False, mensagem=msg)
        return {'sucesso': False, 'mensagem': msg}

    if not cert_db.senha_criptografada:
        msg = f'{cliente.razao_social}: senha do certificado ausente.'
        logger.error(msg)
        LogCaptura.objects.create(cliente=cliente, tipo_documento='TODOS', sucesso=False, mensagem=msg)
        return {'sucesso': False, 'mensagem': msg}

    try:
        senha = decrypt_a1(bytes(cert_db.senha_criptografada)).decode('utf-8')
        import os
        homologacao = os.environ.get('SEFAZ_HOMOLOGACAO', 'True') in ('True', 'true', '1')
        conector = inicializar_cliente_sefaz(
            cliente_obj=cliente,
            senha_certificado=senha,
            homologacao=homologacao,
        )
    except Exception as e:
        msg = f"Falha ao inicializar chaves mTLS/Cofre: {str(e)}"
        logger.error(msg)
        LogCaptura.objects.create(cliente=cliente, tipo_documento='TODOS', sucesso=False, mensagem=msg)
        return {'sucesso': False, 'mensagem': msg}

    # ── MOTOR 1: NF-e & Manifestação ────────────────────────────────────────
    try:
        nfe_service = NFeCapturaService(conector_sefaz=conector, cliente=cliente)
        res_nfe = _esgotar_fila(nfe_service, cliente, 'NFE')
        _manifestar_pendentes(conector, cliente)
        LogCaptura.objects.create(cliente=cliente, tipo_documento='NFE', sucesso=True, mensagem=f"Status: {res_nfe}")
    except Exception as e:
        logger.error(f"Erro no motor NF-e de {cliente.razao_social}: {e}")
        LogCaptura.objects.create(cliente=cliente, tipo_documento='NFE', sucesso=False, mensagem=str(e))

    # ── MOTOR 2: CT-e ───────────────────────────────────────────────────────
    try:
        cte_service = CTeCapturaService(conector_sefaz=conector, cliente=cliente)
        res_cte = _esgotar_fila(cte_service, cliente, 'CTE')
        LogCaptura.objects.create(cliente=cliente, tipo_documento='CTE', sucesso=True, mensagem=f"Status: {res_cte}")
    except Exception as e:
        logger.error(f"Erro no motor CT-e de {cliente.razao_social}: {e}")
        LogCaptura.objects.create(cliente=cliente, tipo_documento='CTE', sucesso=False, mensagem=str(e))

    # ── MOTOR 3: NFS-e Nacional (REST ADN) ──────────────────────────────────
    if cliente.uf.upper() in ('RJ',):
        try:
            nfse_service = NFSeADNCapturaService(conector_sefaz=conector, cliente=cliente)
            res_nfse = _esgotar_fila(nfse_service, cliente, 'NFSE')
            LogCaptura.objects.create(cliente=cliente, tipo_documento='NFSE', sucesso=True, mensagem=f"Status: {res_nfse}")
        except Exception as e:
            logger.warning(f"Erro controlado no motor NFS-e de {cliente.razao_social}: {e}")
            LogCaptura.objects.create(cliente=cliente, tipo_documento='NFSE', sucesso=False, mensagem=f"Erro de Conexão/DNS ADN: {str(e)}")

    return {'sucesso': True, 'mensagem': 'Rotinas de captura finalizadas de forma isolada.'}


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