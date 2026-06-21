import io
import os
import zipfile

from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from .models import Cliente, Certificado, ControleNSU, Documento, Escritorio, LogCaptura, LogAuditoriaNSU, Manifestacao, NotaTratada
from .serializers import (
    ClienteSerializer,
    CertificadoSerializer,
    CertificadoCreateSerializer,
    CertificadoUploadSerializer,
    ControleNSUSerializer,
    DocumentoSerializer,
    DocumentoDetalheSerializer,
    LogCapturaSerializer,
    LogAuditoriaNSUSerializer,
    ManifestacaoSerializer,
    NotaTratadaSerializer,
)
from .filters import DocumentoFilter
from .serializers import EscritorioSerializer


def _qs_por_escritorio(qs, user, campo_escritorio='cliente__escritorio_id'):
    """
    Isolamento multi-tenant: usuários são da equipe do escritório, nunca clientes finais.

    - Superusuário (is_superuser=True, escritorio=None): vê tudo.
    - Usuário de escritório (escritorio_id set): vê só dados do seu escritório.
    - Sem escritorio_id (situação anômala): retorna queryset vazio por segurança.
    """
    if user.is_superuser:
        return qs
    if user.escritorio_id:
        return qs.filter(**{campo_escritorio: user.escritorio_id})
    return qs.none()


class EscritorioViewSet(viewsets.ModelViewSet):
    """CRUD de escritórios de contabilidade. Acesso exclusivo de superadmin."""
    serializer_class = EscritorioSerializer
    permission_classes = [IsAdminUser]
    queryset = Escritorio.objects.all()

    def get_permissions(self):
        # Apenas superusuários podem criar/editar/deletar escritórios
        return [IsAdminUser()]


class ClienteViewSet(viewsets.ModelViewSet):
    """CRUD de clientes fiscais (CNPJs da carteira do escritório)."""
    serializer_class = ClienteSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAdminUser()]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Cliente.objects.all()
        if user.escritorio_id:
            return Cliente.objects.filter(escritorio_id=user.escritorio_id)
        return Cliente.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        escritorio = None if user.is_superuser else user.escritorio
        serializer.save(escritorio=escritorio)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            instance.delete()
        except ProtectedError:
            return Response(
                {'detail': 'Não é possível excluir este cliente pois ele possui registros vinculados (certificados ou documentos).'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='capturar', permission_classes=[IsAdminUser])
    def capturar(self, request, pk=None):
        """POST /api/clientes/{id}/capturar/ — dispara captura NF-e + CT-e + NFS-e síncrona."""
        from fiscal.tasks import capturar_cliente
        cliente = self.get_object()
        resultado = capturar_cliente(cliente)
        http_status = status.HTTP_200_OK if resultado['sucesso'] else status.HTTP_502_BAD_GATEWAY
        return Response(resultado, status=http_status)

    @action(detail=True, methods=['post'], url_path='capturar-nfse', permission_classes=[IsAdminUser])
    def capturar_nfse_direta(self, request, pk=None):
        """
        POST /api/clientes/{id}/capturar-nfse/
        Fallback cirúrgico: busca NFS-e por Chave de Acesso (44 dígitos).
        Dispara varredura NSU incremental no ADN e verifica se a chave apareceu.
        """
        from fiscal.conectores.fabrica import inicializar_cliente_sefaz
        from fiscal.conectores.nfse import NFSeADNCapturaService
        from fiscal.services.cofre import decrypt_a1

        cliente = self.get_object()
        chave = request.data.get('chave_acesso', '').strip()

        if len(chave) != 44:
            return Response(
                {'detail': 'Chave de acesso deve ter exatamente 44 dígitos.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cert_db = cliente.certificados.filter(ativo=True).first()
        if not cert_db or not cert_db.conteudo_criptografado or not cert_db.senha_criptografada:
            return Response(
                {'detail': 'Cliente sem certificado ativo configurado.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            senha = decrypt_a1(bytes(cert_db.senha_criptografada)).decode('utf-8')
            homologacao = os.environ.get('SEFAZ_HOMOLOGACAO', 'True') != 'False'
            conector = inicializar_cliente_sefaz(
                cliente_obj=cliente,
                senha_certificado=senha,
                homologacao=homologacao,
            )
            nfse_service = NFSeADNCapturaService(conector_sefaz=conector, cliente=cliente)
            resultado_str = nfse_service.capturar_por_chave_direta(chave)
        except Exception as e:
            return Response(
                {'sucesso': False, 'mensagem': str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        _mensagens = {
            'SUCESSO':             'NFS-e capturada e armazenada com sucesso.',
            'NOTA_NAO_ENCONTRADA': 'NFS-e não encontrada para a chave informada.',
            'ERRO_CONEXAO':        'Falha de conexão com a API ADN.',
            'ERRO_HTTP':           'API ADN retornou erro HTTP.',
            'XML_INVALIDO':        'XML retornado pela API ADN é inválido ou vazio.',
        }
        sucesso = resultado_str == 'SUCESSO'
        mensagem = _mensagens.get(resultado_str, resultado_str)
        http_status = status.HTTP_200_OK if sucesso else status.HTTP_502_BAD_GATEWAY
        return Response({'sucesso': sucesso, 'mensagem': mensagem}, status=http_status)


class CertificadoViewSet(viewsets.ModelViewSet):
    """CRUD de certificados digitais e upload seguro para o cofre AES."""

    def get_serializer_class(self):
        if self.action == 'create':
            return CertificadoCreateSerializer
        if self.action == 'upload_certificado':
            return CertificadoUploadSerializer
        return CertificadoSerializer

    def create(self, request, *args, **kwargs):
        serializer = CertificadoCreateSerializer(data=request.data)
        if serializer.is_valid():
            cert = serializer.save()
            return Response(CertificadoSerializer(cert).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAdminUser()]

    def get_queryset(self):
        qs = Certificado.objects.select_related('cliente').all()
        return _qs_por_escritorio(qs, self.request.user)

    @action(detail=True, methods=['post'], url_path='upload', permission_classes=[IsAdminUser])
    def upload_certificado(self, request, pk=None):
        """POST /api/certificados/{id}/upload/ — substitui PFX criptografado."""
        certificado = self.get_object()
        serializer = self.get_serializer(certificado, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    'detail': 'Certificado enviado, validado e armazenado com sucesso no cofre AES.',
                    'validade': certificado.validade.strftime('%d/%m/%Y'),
                },
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ControleNSUViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ControleNSUSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ControleNSU.objects.select_related('cliente').all()
        return _qs_por_escritorio(qs, self.request.user)


class DocumentoViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_class = DocumentoFilter
    search_fields = ['chave', 'emitente']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return DocumentoDetalheSerializer
        return DocumentoSerializer

    def get_queryset(self):
        qs = Documento.objects.select_related('cliente').all()
        return _qs_por_escritorio(qs, self.request.user)

    @action(detail=False, methods=['get'], url_path='reconciliar')
    def reconciliar(self, request):
        """
        GET /api/documentos/reconciliar/?cliente=<id>

        Relatório de consistência: capturados vs. maxNSU disponível na SEFAZ/ADN.
        Uma query agregada substitui o N+1 anterior (1 COUNT por ControleNSU).
        """
        cliente_id = request.query_params.get('cliente')

        doc_count = (
            Documento.objects
            .filter(cliente=OuterRef('cliente'), tipo_documento=OuterRef('tipo_documento'))
            .values('cliente')
            .annotate(total=Count('id'))
            .values('total')
        )

        qs = (
            ControleNSU.objects
            .select_related('cliente')
            .annotate(capturados=Subquery(doc_count, output_field=IntegerField()))
        )
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)

        resultado = [
            {
                'cliente':        c.cliente_id,
                'cliente_nome':   c.cliente.razao_social,
                'tipo_documento': c.tipo_documento,
                'ultimo_nsu':     c.ultimo_nsu,
                'max_nsu':        c.max_nsu,
                'capturados':     c.capturados or 0,
                'gap':            max(0, c.max_nsu - c.ultimo_nsu),
                'atualizado_em':  c.atualizado_em,
            }
            for c in qs
        ]
        return Response(resultado)

    @action(detail=False, methods=['get'], url_path='exportar_lote')
    def exportar_lote(self, request):
        """
        GET /api/documentos/exportar_lote/?cliente=<id>&competencia=<AAAA-MM>

        Exige filtro de competência para limitar o volume por requisição.
        Usa iterator(chunk_size) para não carregar o queryset inteiro na RAM.
        O ZIP é montado em memória (BytesIO) e enviado via StreamingHttpResponse
        em chunks de 64 KB — libera memória progressivamente no cliente.
        """
        cliente_id  = request.query_params.get('cliente')
        competencia = request.query_params.get('competencia')

        if not competencia:
            return Response(
                {'detail': 'Parâmetro "competencia" (AAAA-MM) é obrigatório para exportação em lote.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = self.get_queryset().select_related('xml')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)
        qs = qs.filter(competencia=competencia)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for doc in qs.iterator(chunk_size=100):
                try:
                    zf.writestr(f'{doc.chave}.xml', doc.xml.conteudo)
                except Documento.xml.RelatedObjectDoesNotExist:
                    pass
        buf.seek(0)

        def _stream(buffer, chunk=65536):
            while True:
                data = buffer.read(chunk)
                if not data:
                    break
                yield data

        label    = cliente_id if cliente_id else 'todos'
        filename = f'documentos_{label}_{competencia}.zip'
        response = StreamingHttpResponse(_stream(buf), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=['get'], url_path='xml')
    def baixar_xml(self, request, pk=None):
        """GET /api/documentos/{id}/xml/ — retorna o XML bruto."""
        documento = self.get_object()
        try:
            xml = documento.xml
        except Documento.xml.RelatedObjectDoesNotExist:
            return Response(
                {'detail': 'XML nao disponivel para este documento.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return HttpResponse(xml.conteudo, content_type='application/xml; charset=utf-8')


class LogCapturaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LogCapturaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = LogCaptura.objects.select_related('cliente').all()
        return _qs_por_escritorio(qs, self.request.user)


class LogAuditoriaNSUViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/auditoria-nsu/ — histórico de resultados por NSU.
    GET /api/auditoria-nsu/resumo/ — contagens agregadas por resultado (para o card do frontend).
    """
    serializer_class = LogAuditoriaNSUSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = LogAuditoriaNSU.objects.select_related('cliente').all()
        cliente_id = self.request.query_params.get('cliente')
        tipo = self.request.query_params.get('tipo_documento')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)
        if tipo:
            qs = qs.filter(tipo_documento=tipo)
        return _qs_por_escritorio(qs, self.request.user)

    @action(detail=False, methods=['get'], url_path='resumo')
    def resumo(self, request):
        """
        GET /api/auditoria-nsu/resumo/?cliente=<id>&tipo_documento=NFSE

        Retorna contagens por resultado para exibição no card de auditoria NSU.
        """
        from django.db.models import Count
        qs = self.get_queryset()
        contagens = qs.values('resultado').annotate(total=Count('id'))
        por_resultado = {item['resultado']: item['total'] for item in contagens}
        total = sum(por_resultado.values())
        return Response({
            'total': total,
            'por_resultado': por_resultado,
        })


class ManifestacaoViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/manifestacoes/ — histórico de manifestações por documento."""
    serializer_class = ManifestacaoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Manifestacao.objects.select_related('documento', 'documento__cliente').all()
        return _qs_por_escritorio(
            qs, self.request.user,
            campo_escritorio='documento__cliente__escritorio_id',
        )


class NotaTratadaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/notas-tratadas/             — lista paginada com filtros
    GET /api/notas-tratadas/{id}/        — detalhe
    GET /api/notas-tratadas/exportar/    — download Excel (.xlsx)

    Filtros disponíveis: cliente, emitente_cnpj, data_competencia, parecer, papel_nfse
    """
    serializer_class = NotaTratadaSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['emitente_cnpj', 'data_competencia', 'parecer']
    search_fields = ['emitente_nome', 'tomador_nome', 'numero_nfse']

    def get_queryset(self):
        qs = NotaTratada.objects.select_related('documento', 'documento__cliente').all()
        qs = _qs_por_escritorio(qs, self.request.user, campo_escritorio='documento__cliente__escritorio_id')

        cliente_id = self.request.query_params.get('cliente')
        papel = self.request.query_params.get('papel_nfse')
        if cliente_id:
            qs = qs.filter(documento__cliente_id=cliente_id)
        if papel:
            qs = qs.filter(documento__papel_nfse=papel)
        return qs

    @action(detail=False, methods=['get'], url_path='exportar')
    def exportar(self, request):
        """
        GET /api/notas-tratadas/exportar/ — planilha Excel com pareceres fiscais.

        Usa xlsxwriter com constant_memory=True: cada linha é descarregada do heap
        após ser gravada — uso de RAM é O(1) independente do número de linhas.
        """
        import xlsxwriter

        qs = self.filter_queryset(self.get_queryset())

        cabecalhos = [
            'Nº NFS-e', 'Competência', 'Data Proc.', 'CNPJ Emitente', 'Emitente',
            'Doc Tomador', 'Tomador', 'Cód. Tributo', 'Serviço', 'Regime Trib.',
            'Valor Serviço', 'Valor Líquido', 'Ret. PIS', 'Ret. COFINS',
            'Ret. CSLL', 'Ret. IRRF', 'Ret. INSS', 'Parecer', 'Chave Substituta',
        ]

        buf = io.BytesIO()
        wb  = xlsxwriter.Workbook(buf, {'constant_memory': True, 'in_memory': True})
        ws  = wb.add_worksheet('Notas Fiscais')

        fmt_header = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#2563EB',
            'align': 'center', 'border': 1,
        })
        fmt_moeda = wb.add_format({'num_format': '#,##0.00'})

        _CORES = {
            'Válida':                        '#D1FAE5',
            'Válida (DIVERGÊNCIA RETENÇÃO)': '#FEF3C7',
            'Cancelada':                     '#FEE2E2',
            'Substituída':                   '#E0E7FF',
        }
        PARECER_FMTS      = {k: wb.add_format({'bg_color': v})                            for k, v in _CORES.items()}
        PARECER_FMTS_MOEDA = {k: wb.add_format({'bg_color': v, 'num_format': '#,##0.00'}) for k, v in _CORES.items()}

        # Larguras estimadas por coluna (sem varredura reversa — constant_memory não permite)
        larguras = [10, 10, 12, 16, 35, 16, 35, 14, 50, 35, 14, 14, 12, 12, 12, 12, 12, 30, 50]
        for col, (titulo, larg) in enumerate(zip(cabecalhos, larguras)):
            ws.set_column(col, col, larg)
            ws.write(0, col, titulo, fmt_header)

        COLS_MOEDA = {10, 11, 12, 13, 14, 15, 16}

        for row_idx, nota in enumerate(qs.iterator(chunk_size=500), start=1):
            fmt_base  = PARECER_FMTS.get(nota.parecer)
            fmt_money = PARECER_FMTS_MOEDA.get(nota.parecer, fmt_moeda)
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
                fmt = fmt_money if col_idx in COLS_MOEDA else fmt_base
                ws.write(row_idx, col_idx, valor, fmt)

        wb.close()
        buf.seek(0)

        competencia = request.query_params.get('data_competencia', 'todas')
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="relatorio_nfse_{competencia}.xlsx"'
        return response
