from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    EscritorioViewSet,
    ClienteViewSet,
    CertificadoViewSet,
    ControleNSUViewSet,
    DocumentoViewSet,
    LogCapturaViewSet,
    LogAuditoriaNSUViewSet,
    ManifestacaoViewSet,
    NotaTratadaViewSet,
)
from .views_integracao import ExportarPlanilhaView

router = DefaultRouter()
router.register(r'escritorios',    EscritorioViewSet,       basename='escritorio')
router.register(r'clientes',       ClienteViewSet,          basename='cliente')
router.register(r'certificados',   CertificadoViewSet,      basename='certificado')
router.register(r'controles-nsu',  ControleNSUViewSet,      basename='controle-nsu')
router.register(r'documentos',     DocumentoViewSet,        basename='documento')
router.register(r'logs-captura',   LogCapturaViewSet,       basename='logs-captura')
router.register(r'auditoria-nsu',  LogAuditoriaNSUViewSet,  basename='auditoria-nsu')
router.register(r'manifestacoes',  ManifestacaoViewSet,     basename='manifestacao')
router.register(r'notas-tratadas', NotaTratadaViewSet,      basename='nota-tratada')

urlpatterns = router.urls + [
    path('v1/integracao/exportar-planilha/', ExportarPlanilhaView.as_view(), name='integracao-exportar-planilha'),
]
