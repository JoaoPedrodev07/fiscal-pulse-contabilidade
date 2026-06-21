"""
Endpoint externo de integração para clientes que consomem a API via Token.

POST /api/v1/integracao/exportar-planilha/
    Body: { "cnpj": "12345678000199", "mes": 6, "ano": 2025 }
    Auth: Authorization: Token <api-key>
    Response: arquivo .xlsx com duas abas:
        "Notas Fiscais"       — dados tratados + parecer de todas as NFS-e do CNPJ/competência
        "Auditoria de Quebras"— gaps na sequência numérica das notas (possíveis fraudes/falhas)
"""
from __future__ import annotations

import io
import re

from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from .models import NotaTratada, Documento


class ExportarPlanilhaView(APIView):
    """
    Exporta planilha Excel de NFS-e tratadas para integração externa.
    Autenticação via Token DRF (não JWT — apta para sistemas de terceiros).
    """
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        cnpj = request.data.get('cnpj', '').strip()
        mes  = request.data.get('mes')
        ano  = request.data.get('ano')

        erros = {}
        if not re.fullmatch(r'\d{14}', cnpj):
            erros['cnpj'] = 'CNPJ deve conter 14 dígitos numéricos, sem pontuação.'
        try:
            mes_int = int(mes)
            if not 1 <= mes_int <= 12:
                raise ValueError
        except (TypeError, ValueError):
            erros['mes'] = 'Mês inválido. Informe um inteiro de 1 a 12.'
            mes_int = 0
        try:
            ano_int = int(ano)
            if not 2000 <= ano_int <= 2100:
                raise ValueError
        except (TypeError, ValueError):
            erros['ano'] = 'Ano inválido. Informe um inteiro entre 2000 e 2100.'
            ano_int = 0

        if erros:
            return Response({'erros': erros}, status=status.HTTP_400_BAD_REQUEST)

        competencia_mm_aaaa = f'{mes_int:02d}/{ano_int}'

        notas_qs = (
            NotaTratada.objects
            .filter(emitente_cnpj=cnpj, data_competencia=competencia_mm_aaaa)
            .select_related('documento')
            .order_by('numero_nfse')
        )

        buf = io.BytesIO()
        _gerar_xlsx(buf, notas_qs, cnpj, competencia_mm_aaaa)
        buf.seek(0)

        filename = f'relatorio_{cnpj}_{ano_int}-{mes_int:02d}.xlsx'
        from django.http import HttpResponse
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


def _gerar_xlsx(buf: io.BytesIO, notas_qs, cnpj: str, competencia: str) -> None:
    """
    Gera o arquivo .xlsx em buf usando xlsxwriter com constant_memory=True.
    Cada linha é gravada e imediatamente descartada do heap — uso de RAM O(1).
    A aba de Auditoria de Quebras exige O(N) memória para detectar gaps,
    portanto é construída separadamente em uma segunda passagem.
    """
    import xlsxwriter

    wb = xlsxwriter.Workbook(buf, {'constant_memory': True, 'in_memory': True})

    # ── Formatos compartilhados ────────────────────────────────────────────────
    fmt_hdr_azul = wb.add_format({
        'bold': True, 'font_color': 'white', 'bg_color': '#2563EB',
        'align': 'center', 'border': 1,
    })
    fmt_hdr_verm = wb.add_format({
        'bold': True, 'font_color': 'white', 'bg_color': '#DC2626',
        'align': 'center', 'border': 1,
    })
    fmt_moeda = wb.add_format({'num_format': '#,##0.00'})

    _CORES = {
        'Válida':                        '#D1FAE5',
        'Válida (DIVERGÊNCIA RETENÇÃO)': '#FEF3C7',
        'Cancelada':                     '#FEE2E2',
        'Substituída':                   '#E0E7FF',
    }
    parecer_fmt      = {k: wb.add_format({'bg_color': v})                              for k, v in _CORES.items()}
    parecer_fmt_moed = {k: wb.add_format({'bg_color': v, 'num_format': '#,##0.00'})   for k, v in _CORES.items()}

    # ── Aba 1: Notas Fiscais ──────────────────────────────────────────────────
    ws1 = wb.add_worksheet('Notas Fiscais')

    cabecalhos = [
        'Nº NFS-e', 'Competência', 'Data Proc.', 'CNPJ Emitente', 'Emitente',
        'Doc Tomador', 'Tomador', 'Cód. Tributo', 'Serviço', 'Regime Trib.',
        'Valor Serviço', 'Valor Líquido',
        'Ret. PIS', 'Ret. COFINS', 'Ret. CSLL', 'Ret. IRRF', 'Ret. INSS',
        'Parecer', 'Chave Substituta',
    ]
    larguras = [10, 10, 12, 16, 35, 16, 35, 14, 50, 35, 14, 14, 12, 12, 12, 12, 12, 30, 50]
    COLS_MOEDA = {10, 11, 12, 13, 14, 15, 16}

    for col, (titulo, larg) in enumerate(zip(cabecalhos, larguras)):
        ws1.set_column(col, col, larg)
        ws1.write(0, col, titulo, fmt_hdr_azul)

    numeros_vistos: list[int] = []

    for row_idx, nota in enumerate(notas_qs.iterator(chunk_size=500), start=1):
        try:
            numeros_vistos.append(int(nota.numero_nfse))
        except (ValueError, TypeError):
            pass

        fp  = parecer_fmt.get(nota.parecer)
        fpm = parecer_fmt_moed.get(nota.parecer, fmt_moeda)
        linha = [
            nota.numero_nfse,
            nota.data_competencia,
            nota.data_processamento,
            nota.emitente_cnpj,
            nota.emitente_nome,
            nota.tomador_doc,
            nota.tomador_nome,
            nota.codigo_tributo,
            nota.descricao_servico,
            nota.regime_trib,
            float(nota.valor_servico) if nota.valor_servico is not None else '',
            float(nota.valor_liquido) if nota.valor_liquido is not None else '',
            float(nota.ret_pis)       if nota.ret_pis       is not None else '',
            float(nota.ret_cofins)    if nota.ret_cofins    is not None else '',
            float(nota.ret_csll)      if nota.ret_csll      is not None else '',
            float(nota.ret_irrf)      if nota.ret_irrf      is not None else '',
            float(nota.ret_inss)      if nota.ret_inss      is not None else '',
            nota.parecer,
            nota.chave_substituta,
        ]
        for col_idx, valor in enumerate(linha):
            ws1.write(row_idx, col_idx, valor, fpm if col_idx in COLS_MOEDA else fp)

    # ── Aba 2: Auditoria de Quebras ───────────────────────────────────────────
    # Requer ordenação e varredura linear — O(N log N) inevitável.
    # N aqui é o número de notas do CNPJ/competência, não o banco inteiro.
    ws2 = wb.add_worksheet('Auditoria de Quebras')

    cab2    = ['Nº Esperado', 'Nº Anterior', 'Nº Seguinte', 'Qtd. Faltando', 'Observação']
    larg2   = [14, 14, 14, 16, 60]
    for col, (titulo, larg) in enumerate(zip(cab2, larg2)):
        ws2.set_column(col, col, larg)
        ws2.write(0, col, titulo, fmt_hdr_verm)

    numeros_vistos.sort()
    gaps_row = 1
    if len(numeros_vistos) >= 2:
        for i in range(len(numeros_vistos) - 1):
            anterior = numeros_vistos[i]
            proximo  = numeros_vistos[i + 1]
            if proximo - anterior > 1:
                for faltando in range(anterior + 1, proximo):
                    ws2.write_row(gaps_row, 0, [
                        faltando,
                        anterior,
                        proximo,
                        proximo - anterior - 1,
                        'NSU ausente — verificar cancelamento ou captura pendente',
                    ])
                    gaps_row += 1

    if gaps_row == 1:
        ws2.write(1, 0, 'Nenhuma quebra detectada na sequência numérica.')

    wb.close()
