import io
import os
import zipfile

from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend

from .models import Cliente, Certificado, ControleNSU, Documento, Escritorio, LogCaptura, Manifestacao
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
        Permite ao contador verificar gaps antes do fechamento fiscal.

        Campos por tipo de documento:
          - ultimo_nsu: ponteiro atual do banco
          - max_nsu: total disponível na fonte
          - capturados: documentos salvos
          - gap: NSUs ainda não processados (max_nsu - ultimo_nsu)
        """
        cliente_id = request.query_params.get('cliente')
        qs = ControleNSU.objects.select_related('cliente').all()
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)

        resultado = []
        for c in qs:
            capturados = Documento.objects.filter(
                cliente=c.cliente,
                tipo_documento=c.tipo_documento,
            ).count()
            resultado.append({
                'cliente':        c.cliente_id,
                'cliente_nome':   c.cliente.razao_social,
                'tipo_documento': c.tipo_documento,
                'ultimo_nsu':     c.ultimo_nsu,
                'max_nsu':        c.max_nsu,
                'capturados':     capturados,
                'gap':            max(0, c.max_nsu - c.ultimo_nsu),
                'atualizado_em':  c.atualizado_em,
            })

        return Response(resultado)

    @action(detail=False, methods=['get'], url_path='exportar_lote')
    def exportar_lote(self, request):
        """GET /api/documentos/exportar_lote/?cliente=<id>&competencia=<AAAA-MM>"""
        cliente_id = request.query_params.get('cliente')
        competencia = request.query_params.get('competencia')

        qs = self.get_queryset().select_related('xml')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)
        if competencia:
            qs = qs.filter(competencia=competencia)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for doc in qs:
                try:
                    zf.writestr(f'{doc.chave}.xml', doc.xml.conteudo)
                except Documento.xml.RelatedObjectDoesNotExist:
                    pass
        buffer.seek(0)

        sufixo = competencia if competencia else 'todos'
        label = cliente_id if cliente_id else 'todos'
        filename = f'documentos_{label}_{sufixo}.zip'
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
        qs = LogCaptura.objects.select_related('cliente').all()
        return _qs_por_escritorio(qs, self.request.user)


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
