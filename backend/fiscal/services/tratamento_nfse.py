"""
Tratamento fiscal de NFS-e ADN.

Extrai campos estruturados de um XML de NFS-e e devolve um dict com os dados
tratados e o 'parecer' fiscal.  Sem dependências de filesystem — recebe o XML
como string e devolve dados puros.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

NS = {'nfse': 'http://www.sped.fazenda.gov.br/nfse'}

# Alíquotas padrão CSRF (PIS + COFINS + CSLL retidos na fonte)
_ALIQ_PIS     = Decimal('0.0065')
_ALIQ_COFINS  = Decimal('0.03')
_ALIQ_CSLL    = Decimal('0.01')
_TOLERANCIA   = Decimal('0.05')


def _text(root: ET.Element, path: str) -> str:
    elem = root.find(path, NS)
    return (elem.text or '').strip() if elem is not None else ''


def _decimal(valor: str) -> Decimal | None:
    if not valor or valor == 'N/A':
        return None
    try:
        return Decimal(valor.replace(',', '.'))
    except InvalidOperation:
        return None


def _formatar_data(raw: str) -> str:
    """'YYYY-MM-DD...' → 'DD/MM/AAAA'"""
    if not raw:
        return ''
    try:
        data = raw.split('T')[0]
        a, m, d = data.split('-')
        return f'{d}/{m}/{a}'
    except Exception:
        return raw


def _formatar_competencia(raw: str) -> str:
    """'YYYY-MM' ou 'YYYY-MM-DD' → 'MM/AAAA'"""
    if not raw:
        return ''
    try:
        partes = raw.split('-')
        return f'{partes[1]}/{partes[0]}'
    except Exception:
        return raw


def _regime_trib(codigo: str) -> str:
    mapa = {
        '0': 'Nenhum',
        '1': 'Microempresa Municipal',
        '2': 'Estimativa',
        '3': 'Sociedade de Profissionais',
        '4': 'Cooperativa',
        '5': 'Microempresário Individual (MEI)',
        '6': 'Microempresário e Empresa de Pequeno Porte (ME EPP)',
    }
    return mapa.get(codigo, codigo)


def extrair_dados_nfse(
    xml_content: str,
    status: str,
    papel_nfse: str,
    root: ET.Element | None = None,
) -> dict:
    """
    Extrai dados fiscais de um XML NFS-e ADN e retorna dict com campos tratados.

    Args:
        xml_content: conteúdo XML completo como string UTF-8
        status:      status já determinado pelo conector (COMPLETO/CANCELADO/SUBSTITUIDO)
        papel_nfse:  TOMADOR ou EMITENTE (já determinado pelo conector)
        root:        árvore ET já parseada — evita re-parse quando disponível

    Returns dict com todas as colunas de NotaTratada + 'parecer'.
    Retorna dict vazio em caso de XML inválido.
    """
    if root is None:
        try:
            root = ET.fromstring(xml_content.encode('utf-8') if isinstance(xml_content, str) else xml_content)
        except ET.ParseError as exc:
            logger.warning('tratamento_nfse: XML inválido — %s', exc)
            return {}

    t = lambda path: _text(root, path)

    # ── Identificação ─────────────────────────────────────────────────
    numero_nfse = t('.//nfse:nNFSe')

    # ── Datas ─────────────────────────────────────────────────────────
    comp_raw       = t('.//nfse:dCompet')
    data_competencia   = _formatar_competencia(comp_raw)
    data_processamento = _formatar_data(t('.//nfse:dhProc'))

    # ── Emitente ──────────────────────────────────────────────────────
    emitente_cnpj = t('.//nfse:emit/nfse:CNPJ')
    emitente_nome = t('.//nfse:emit/nfse:xNome')

    # ── Tomador ───────────────────────────────────────────────────────
    tomador_nome = (
        t('.//nfse:DPS/nfse:infDPS/nfse:toma/nfse:xNome')
        or t('.//nfse:toma/nfse:xNome')
    )
    tomador_doc = (
        t('.//nfse:DPS/nfse:infDPS/nfse:toma/nfse:CNPJ')
        or t('.//nfse:DPS/nfse:infDPS/nfse:toma/nfse:CPF')
        or t('.//nfse:toma/nfse:CNPJ')
        or t('.//nfse:toma/nfse:CPF')
        or t('.//nfse:toma/nfse:identificacaoTomador/nfse:cpfCnpj/nfse:Cnpj')
        or t('.//nfse:toma/nfse:identificacaoTomador/nfse:cpfCnpj/nfse:Cpf')
    )

    # ── Serviço ───────────────────────────────────────────────────────
    codigo_tributo = (
        t('.//nfse:DPS/nfse:infDPS/nfse:serv/nfse:cTribNac')
        or t('.//nfse:cTribNac')
        or t('.//nfse:serv/nfse:ItemListaServico')
    )
    descricao_servico = (
        t('.//nfse:DPS/nfse:infDPS/nfse:serv/nfse:cServ/nfse:xDescServ')
        or t('.//nfse:serv/nfse:cServ/nfse:xDescServ')
    )

    # ── Regime especial de tributação ─────────────────────────────────
    reg_raw = (
        t('.//nfse:DPS/nfse:infDPS/nfse:regEspTrib')
        or t('.//nfse:regEspTrib')
    )
    regime_trib = _regime_trib(reg_raw)

    # ── Valores ───────────────────────────────────────────────────────
    v_serv_raw = (
        t('.//nfse:DPS/nfse:infDPS/nfse:valores/nfse:vServPrest/nfse:vServ')
        or t('.//nfse:valores/nfse:vServ')
    )
    valor_servico = _decimal(v_serv_raw)
    valor_liquido = _decimal(t('.//nfse:valores/nfse:vLiq'))

    # PIS / COFINS (considerando tpRetPisCofins)
    tp_ret = t('.//nfse:piscofins/nfse:tpRetPisCofins')
    if tp_ret == '2':
        ret_pis   = None
        ret_cofins = None
    elif tp_ret == '1':
        ret_pis   = _decimal(t('.//nfse:vRetPis')   or t('.//nfse:piscofins/nfse:vPis')   or t('.//nfse:vPis'))
        ret_cofins = _decimal(t('.//nfse:vRetCofins') or t('.//nfse:piscofins/nfse:vCofins') or t('.//nfse:vCofins'))
    else:
        ret_pis   = _decimal(t('.//nfse:vRetPis')   or t('.//nfse:vPis'))
        ret_cofins = _decimal(t('.//nfse:vRetCofins') or t('.//nfse:vCofins'))

    ret_csll = _decimal(t('.//nfse:vRetCSLL') or t('.//nfse:vCsll'))
    ret_irrf = _decimal(t('.//nfse:vRetIRRF') or t('.//nfse:vIr'))
    ret_inss = _decimal(
        t('.//nfse:vRetINSS') or t('.//nfse:vInss') or t('.//nfse:valores/nfse:vInss')
    )

    # ── Substituição ──────────────────────────────────────────────────
    ch_substda_raw = t('.//nfse:DPS/nfse:infDPS/nfse:subst/nfse:chSubstda')
    # chave da nota que ESTA nota substitui (limpa prefixo "NFS")
    chave_que_esta_substitui = ch_substda_raw.replace('NFS', '') if ch_substda_raw else ''

    # ── Parecer fiscal ────────────────────────────────────────────────
    parecer = _calcular_parecer(status, valor_servico, ret_csll, ret_pis, ret_cofins)

    # Corrigir PIS/COFINS se detectado como bundle CSRF
    if parecer == 'Válida' and valor_servico and ret_csll:
        calc_csll   = (valor_servico * _ALIQ_CSLL).quantize(Decimal('0.01'))
        calc_pis    = (valor_servico * _ALIQ_PIS).quantize(Decimal('0.01'))
        calc_cofins = (valor_servico * _ALIQ_COFINS).quantize(Decimal('0.01'))
        csrf_total  = calc_pis + calc_cofins + calc_csll
        if abs(ret_csll - csrf_total) <= _TOLERANCIA:
            # CSLL estava acumulando PIS+COFINS+CSLL — desagregar
            ret_pis    = calc_pis
            ret_cofins = calc_cofins
            ret_csll   = calc_csll

    return {
        'numero_nfse':        numero_nfse,
        'data_competencia':   data_competencia,
        'data_processamento': data_processamento,
        'emitente_cnpj':      emitente_cnpj,
        'emitente_nome':      emitente_nome,
        'tomador_doc':        tomador_doc,
        'tomador_nome':       tomador_nome,
        'codigo_tributo':     codigo_tributo,
        'descricao_servico':  descricao_servico,
        'regime_trib':        regime_trib,
        'valor_servico':      valor_servico,
        'valor_liquido':      valor_liquido,
        'ret_pis':            ret_pis,
        'ret_cofins':         ret_cofins,
        'ret_csll':           ret_csll,
        'ret_irrf':           ret_irrf,
        'ret_inss':           ret_inss,
        'parecer':            parecer,
        'chave_que_esta_substitui': chave_que_esta_substitui,
    }


def _calcular_parecer(
    status: str,
    valor_servico: Decimal | None,
    ret_csll: Decimal | None,
    ret_pis: Decimal | None,
    ret_cofins: Decimal | None,
) -> str:
    if status == 'CANCELADO':
        return 'Cancelada'
    if status == 'SUBSTITUIDO':
        return 'Substituída'
    if valor_servico and ret_csll:
        calc_csll = valor_servico * _ALIQ_CSLL
        csrf_total = valor_servico * (_ALIQ_PIS + _ALIQ_COFINS + _ALIQ_CSLL)
        # nem bundle nem CSLL correto → divergência
        if (abs(ret_csll - csrf_total) > _TOLERANCIA and abs(ret_csll - calc_csll) > _TOLERANCIA):
            return 'Válida (DIVERGÊNCIA RETENÇÃO)'
    return 'Válida'
