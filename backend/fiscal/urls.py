from rest_framework.routers import DefaultRouter
from .views import (
    EscritorioViewSet,
    ClienteViewSet,
    CertificadoViewSet,
    ControleNSUViewSet,
    DocumentoViewSet,
    LogCapturaViewSet,
    ManifestacaoViewSet,
)

router = DefaultRouter()
router.register(r'escritorios',    EscritorioViewSet,    basename='escritorio')
router.register(r'clientes',       ClienteViewSet,       basename='cliente')
router.register(r'certificados',   CertificadoViewSet,   basename='certificado')
router.register(r'controles-nsu',  ControleNSUViewSet,   basename='controle-nsu')
router.register(r'documentos',     DocumentoViewSet,     basename='documento')
router.register(r'logs-captura',   LogCapturaViewSet,    basename='logs-captura')
router.register(r'manifestacoes',  ManifestacaoViewSet,  basename='manifestacao')

urlpatterns = router.urls
