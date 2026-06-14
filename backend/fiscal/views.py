import io
import zipfile

from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend

from .models import Cliente, Certificado, ControleNSU, Documento, LogCaptura
from .serializers import (
    ClienteSerializer,
    CertificadoSerializer,
    ControleNSUSerializer,
    DocumentoSerializer,
    DocumentoDetalheSerializer,
    LogCapturaSerializer,
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


class CertificadoViewSet(viewsets.ModelViewSet):
    """CRUD de certificados digitais (apenas metadados — o A1 nunca trafega)."""
    serializer_class = CertificadoSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAdminUser()]

    def get_queryset(self):
        return Certificado.objects.select_related('cliente').all()


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
