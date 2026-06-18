import io
import zipfile

from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend

from .models import Cliente, Certificado, ControleNSU, Documento, LogCaptura, Manifestacao
from .serializers import (
    ClienteSerializer,
    CertificadoSerializer,
    CertificadoCreateSerializer,
    CertificadoUploadSerializer,
    ControleNSUSerializer,
    DocumentoSerializer,
    DocumentoDetalheSerializer,
    LogCapturaSerializer,
    ManifestacaoSerializer,
)
from .filters import DocumentoFilter


class ClienteViewSet(viewsets.ModelViewSet):
    """CRUD de clientes fiscais (CNPJs da carteira). Acesso restrito a staff."""
    serializer_class = ClienteSerializer
    queryset = Cliente.objects.all()

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAdminUser()]

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
        """POST /api/clientes/{id}/capturar/ — dispara captura SEFAZ síncrona para um cliente."""
        from fiscal.tasks import capturar_cliente
        cliente = self.get_object()
        resultado = capturar_cliente(cliente)
        http_status = status.HTTP_200_OK if resultado['sucesso'] else status.HTTP_502_BAD_GATEWAY
        return Response(resultado, status=http_status)


class CertificadoViewSet(viewsets.ModelViewSet):
    """CRUD de certificados digitais e upload seguro para o cofre AES."""
    
    def get_serializer_class(self):
        if self.action == 'upload_certificado':
            return CertificadoUploadSerializer
        return CertificadoSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAdminUser()]

    def get_queryset(self):
        return Certificado.objects.select_related('cliente').all()

    @action(detail=True, methods=['post'], url_path='upload', permission_classes=[IsAdminUser])
    def upload_certificado(self, request, pk=None):
        """
        POST /api/certificados/{id}/upload/
        Recebe multipart/form-data com 'arquivo' (.pfx) e 'senha'.
        Valida na memória RAM e persiste de forma criptografada no banco.
        """
        certificado = self.get_object()
        # Passa o serializer dinâmico usando o método apropriado do DRF
        serializer = self.get_serializer(certificado, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "detail": "Certificado enviado, validado e armazenado com sucesso no cofre AES.",
                    "validade": certificado.validade.strftime("%d/%m/%Y")
                }, 
                status=status.HTTP_200_OK
            )
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ControleNSUViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ControleNSUSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ControleNSU.objects.select_related('cliente').all()


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
        return Documento.objects.select_related('cliente').all()

    @action(detail=False, methods=['get'], url_path='exportar_lote')
    def exportar_lote(self, request):
        """GET /api/documentos/exportar_lote/?cliente=<id>&competencia=<AAAA-MM>"""
        cliente_id = request.query_params.get('cliente')
        competencia = request.query_params.get('competencia')

        if not cliente_id or not competencia:
            return Response(
                {'detail': 'Os parametros "cliente" e "competencia" sao obrigatorios.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = (
            self.get_queryset()
            .filter(cliente_id=cliente_id, competencia=competencia)
            .select_related('xml')
        )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for doc in qs:
                try:
                    zf.writestr(f'{doc.chave}.xml', doc.xml.conteudo)
                except Documento.xml.RelatedObjectDoesNotExist:
                    pass
        buffer.seek(0)

        filename = f'documentos_{cliente_id}_{competencia}.zip'
        response = HttpResponse(buffer.read(), content_type='application/zip')
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
        return LogCaptura.objects.select_related('cliente').all()


class ManifestacaoViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/manifestacoes/ — histórico de manifestações por documento."""
    serializer_class = ManifestacaoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Manifestacao.objects.select_related(
            'documento', 'documento__cliente'
        ).all()
