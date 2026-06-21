import re

from rest_framework import viewsets, status, exceptions
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler as drf_exception_handler
from rest_framework_simplejwt.views import TokenObtainPairView

from fiscal.models import Escritorio
from .models import User
from .serializers import TokenObtainPairPTSerializer, UserCreateSerializer, UserSerializer


# ── Mensagens de erro em português ────────────────────────────────────────────

_MSG_PT = {
    'authentication_failed':          'Credenciais incorretas. Verifique o usuário e a senha.',
    'not_authenticated':              'Autenticação necessária. Faça login para continuar.',
    'permission_denied':              'Você não tem permissão para realizar esta ação.',
    'not_found':                      'Recurso não encontrado.',
    'method_not_allowed':             'Método não permitido.',
    'not_acceptable':                 'Formato de resposta não suportado.',
    'unsupported_media_type':         'Tipo de mídia não suportado.',
    'throttled':                      'Muitas requisições. Aguarde um momento antes de tentar novamente.',
    'invalid':                        'Dados inválidos.',
    'token_not_valid':                'Token inválido ou expirado. Faça login novamente.',
}


def exception_handler_pt(exc, context):
    """
    Substitui as mensagens de erro padrão do DRF por versões em português.
    Registrar em settings.py: REST_FRAMEWORK['EXCEPTION_HANDLER'].
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.AuthenticationFailed):
        response.data = {'detail': _MSG_PT['authentication_failed']}
    elif isinstance(exc, exceptions.NotAuthenticated):
        response.data = {'detail': _MSG_PT['not_authenticated']}
    elif isinstance(exc, exceptions.PermissionDenied):
        response.data = {'detail': _MSG_PT['permission_denied']}
    elif isinstance(exc, exceptions.NotFound):
        response.data = {'detail': _MSG_PT['not_found']}
    elif isinstance(exc, exceptions.MethodNotAllowed):
        response.data = {'detail': _MSG_PT['method_not_allowed']}
    elif isinstance(exc, exceptions.Throttled):
        response.data = {'detail': _MSG_PT['throttled']}
    elif response.status_code == 401:
        # Pega qualquer outro 401 (ex: token expirado do SimpleJWT)
        detail = response.data.get('detail', '')
        english_401_msgs = {
            'No active account found with the given credentials',
            'Given token not valid for any token type',
            'Token is invalid or expired',
            'Token has wrong type',
            'User not found',
        }
        if str(detail) in english_401_msgs:
            response.data['detail'] = _MSG_PT.get(
                'token_not_valid' if 'token' in str(detail).lower() else 'authentication_failed',
                _MSG_PT['authentication_failed'],
            )

    return response


# ── Views ──────────────────────────────────────────────────────────────────────

class TokenObtainPairPTView(TokenObtainPairView):
    """POST /api/token/ com mensagens de erro em português."""
    serializer_class = TokenObtainPairPTSerializer


class UserViewSet(viewsets.ModelViewSet):

    def get_queryset(self):
        qs = User.objects.all()
        if not self.request.user.is_staff:
            qs = qs.filter(pk=self.request.user.pk)
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_permissions(self):
        if self.action in ('create', 'list', 'destroy'):
            return [IsAdminUser()]
        return [IsAuthenticated()]

    @action(detail=False, methods=['get', 'put', 'patch'], permission_classes=[IsAuthenticated])
    def me(self, request):
        """GET/PUT/PATCH /api/users/me/"""
        user = request.user
        if request.method == 'GET':
            return Response(UserSerializer(user).data)

        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RegistroEscritorioView(APIView):
    """
    POST /api/registro/  — público, sem autenticação.
    Cria um Escritório de contabilidade e seu usuário administrador em uma única chamada.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data

        razao_social = (data.get('razao_social') or '').strip()
        cnpj         = re.sub(r'\D', '', data.get('cnpj') or '')
        username     = (data.get('username') or '').strip()
        email        = (data.get('email') or '').strip().lower()
        senha        = data.get('senha') or ''
        confirmar    = data.get('confirmar_senha') or ''

        erros = {}

        if not razao_social:
            erros['razao_social'] = 'Razão social é obrigatória.'
        if not re.fullmatch(r'\d{14}', cnpj):
            erros['cnpj'] = 'CNPJ deve ter 14 dígitos numéricos.'
        elif Escritorio.objects.filter(cnpj=cnpj).exists():
            erros['cnpj'] = 'Já existe um escritório cadastrado com este CNPJ.'
        if not username:
            erros['username'] = 'Nome de usuário é obrigatório.'
        elif User.objects.filter(username=username).exists():
            erros['username'] = 'Este nome de usuário já está em uso.'
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            erros['email'] = 'Informe um e-mail válido.'
        elif User.objects.filter(email=email).exists():
            erros['email'] = 'Este e-mail já está cadastrado.'
        if len(senha) < 8:
            erros['senha'] = 'A senha deve ter pelo menos 8 caracteres.'
        elif senha != confirmar:
            erros['confirmar_senha'] = 'As senhas não coincidem.'

        if erros:
            return Response(erros, status=status.HTTP_400_BAD_REQUEST)

        escritorio = Escritorio.objects.create(
            razao_social=razao_social,
            cnpj=cnpj,
            ativo=True,
        )
        User.objects.create_user(
            username=username,
            email=email,
            password=senha,
            is_staff=True,
            is_active=True,
            escritorio=escritorio,
        )

        return Response(
            {'detail': 'Escritório cadastrado com sucesso. Faça login para continuar.'},
            status=status.HTTP_201_CREATED,
        )
