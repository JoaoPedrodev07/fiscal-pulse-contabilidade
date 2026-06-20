"""
Suíte de testes — app users.

Garante que a criacao de contas e o endpoint /me/ estejam corretos
e que a porta de entrada do sistema seja segura.

Rodar:
    python manage.py test users --verbosity=2
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


def make_staff(username="admin_user"):
    return User.objects.create_user(username=username, password="pass", is_staff=True)


def make_operator(username="op_user"):
    return User.objects.create_user(username=username, password="pass", is_staff=False)


# ──────────────────────────────────────────────────────────────────────────────
# Criacao de usuario — agora exige is_staff (AllowAny removido)
# ──────────────────────────────────────────────────────────────────────────────

class CriacaoUsuarioTest(APITestCase):

    def test_criar_sem_auth_retorna_401(self):
        res = self.client.post(
            "/api/users/",
            {"username": "novo", "email": "novo@x.com", "password": "senha_segura"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_criar_como_operador_retorna_403(self):
        op = make_operator()
        self.client.force_authenticate(user=op)
        res = self.client.post(
            "/api/users/",
            {"username": "novo", "email": "novo@x.com", "password": "senha_segura"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_criar_como_staff_retorna_201(self):
        staff = make_staff()
        self.client.force_authenticate(user=staff)
        res = self.client.post(
            "/api/users/",
            {"username": "novo_func", "email": "func@x.com", "password": "senha_segura"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["username"], "novo_func")

    def test_senha_nao_retorna_na_resposta(self):
        """Nunca expor a senha — nem hash — na resposta da API."""
        staff = make_staff()
        self.client.force_authenticate(user=staff)
        res = self.client.post(
            "/api/users/",
            {"username": "novo_func2", "email": "func2@x.com", "password": "senha_segura"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("password", res.data)

    def test_usuario_criado_nao_e_staff_por_padrao(self):
        staff = make_staff()
        self.client.force_authenticate(user=staff)
        res = self.client.post(
            "/api/users/",
            {"username": "novo_op", "email": "op@x.com", "password": "senha_segura"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        criado = User.objects.get(username="novo_op")
        self.assertFalse(criado.is_staff)

    def test_username_duplicado_retorna_400(self):
        make_staff(username="duplicado")
        staff = make_staff(username="outro_staff")
        self.client.force_authenticate(user=staff)
        res = self.client.post(
            "/api/users/",
            {"username": "duplicado", "email": "dup@x.com", "password": "senha_segura"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint /me/
# ──────────────────────────────────────────────────────────────────────────────

class MeEndpointTest(APITestCase):

    def test_sem_auth_retorna_401(self):
        res = self.client.get("/api/users/me/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retorna_usuario_logado(self):
        user = make_operator()
        self.client.force_authenticate(user=user)
        res = self.client.get("/api/users/me/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["username"], user.username)

    def test_nao_retorna_senha(self):
        user = make_operator(username="me_user")
        self.client.force_authenticate(user=user)
        res = self.client.get("/api/users/me/")
        self.assertNotIn("password", res.data)

    def test_inclui_is_staff(self):
        """Frontend usa is_staff para mostrar/esconder menus de admin."""
        staff = make_staff(username="staff_me")
        op = make_operator(username="op_me")

        self.client.force_authenticate(user=staff)
        res_staff = self.client.get("/api/users/me/")
        self.assertTrue(res_staff.data["is_staff"])

        self.client.force_authenticate(user=op)
        res_op = self.client.get("/api/users/me/")
        self.assertFalse(res_op.data["is_staff"])

    def test_patch_atualiza_email(self):
        """UserSerializer tem email como campo editavel."""
        user = make_operator(username="patch_user")
        self.client.force_authenticate(user=user)
        res = self.client.patch("/api/users/me/", {"email": "novo@email.com"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.email, "novo@email.com")


# ──────────────────────────────────────────────────────────────────────────────
# Listagem de usuarios — restrita a staff
# ──────────────────────────────────────────────────────────────────────────────

class ListaUsuariosTest(APITestCase):

    def test_operador_nao_pode_listar_todos(self):
        op = make_operator()
        self.client.force_authenticate(user=op)
        res = self.client.get("/api/users/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_pode_listar_todos(self):
        make_staff(username="s1")
        make_operator(username="o1")
        staff = make_staff(username="s2")
        self.client.force_authenticate(user=staff)
        res = self.client.get("/api/users/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_sem_auth_retorna_401(self):
        res = self.client.get("/api/users/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint público de registro de escritório — POST /api/registro/
# ──────────────────────────────────────────────────────────────────────────────

PAYLOAD_VALIDO = {
    "razao_social": "Contabilidade Teste LTDA",
    "cnpj": "12345678000199",
    "username": "conta.teste",
    "email": "contato@teste.com.br",
    "senha": "senha_segura123",
    "confirmar_senha": "senha_segura123",
}


class RegistroEscritorioTest(APITestCase):
    """
    POST /api/registro/ cria Escritório + usuário admin sem exigir autenticação.
    Qualquer erro de validação deve retornar 400 com a chave do campo afetado.
    """

    URL = "/api/registro/"

    def _post(self, **overrides):
        payload = {**PAYLOAD_VALIDO, **overrides}
        return self.client.post(self.URL, payload, format="json")

    # -- Sucesso ------------------------------------------------------------------

    def test_sucesso_retorna_201(self):
        res = self._post()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_sucesso_cria_escritorio_no_banco(self):
        from fiscal.models import Escritorio
        self._post()
        self.assertTrue(Escritorio.objects.filter(cnpj="12345678000199").exists())

    def test_sucesso_cria_usuario_is_staff(self):
        self._post()
        u = User.objects.get(username="conta.teste")
        self.assertTrue(u.is_staff)

    def test_sucesso_usuario_vinculado_ao_escritorio(self):
        from fiscal.models import Escritorio
        self._post()
        escritorio = Escritorio.objects.get(cnpj="12345678000199")
        u = User.objects.get(username="conta.teste")
        self.assertEqual(u.escritorio, escritorio)

    def test_sucesso_usuario_com_email_correto(self):
        self._post()
        u = User.objects.get(username="conta.teste")
        self.assertEqual(u.email, "contato@teste.com.br")

    def test_sucesso_sem_autenticacao(self):
        """Endpoint é público — não exige token."""
        res = self._post()
        self.assertNotEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_resposta_contem_detail(self):
        res = self._post()
        self.assertIn("detail", res.data)

    # -- Validação do escritório --------------------------------------------------

    def test_razao_social_vazia_retorna_400(self):
        res = self._post(razao_social="")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("razao_social", res.data)

    def test_cnpj_com_menos_de_14_digitos_retorna_400(self):
        res = self._post(cnpj="1234567800019")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cnpj", res.data)

    def test_cnpj_com_mais_de_14_digitos_retorna_400(self):
        res = self._post(cnpj="123456780001999")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cnpj", res.data)

    def test_cnpj_com_pontuacao_e_aceito(self):
        """Frontend envia CNPJ formatado; o backend deve aceitar e limpar."""
        res = self._post(cnpj="12.345.678/0001-99")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_cnpj_duplicado_retorna_400(self):
        self._post()
        res = self._post(username="outro.user", email="outro@x.com")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cnpj", res.data)

    # -- Validação do acesso ------------------------------------------------------

    def test_username_vazio_retorna_400(self):
        res = self._post(username="")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", res.data)

    def test_username_duplicado_retorna_400(self):
        self._post()
        res = self._post(cnpj="98765432000110", email="outro@x.com")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", res.data)

    def test_email_invalido_retorna_400(self):
        res = self._post(email="nao-e-um-email")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", res.data)

    def test_email_duplicado_retorna_400(self):
        self._post()
        res = self._post(cnpj="98765432000110", username="outro.user")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", res.data)

    def test_senha_curta_retorna_400(self):
        res = self._post(senha="curta", confirmar_senha="curta")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("senha", res.data)

    def test_senhas_diferentes_retornam_400(self):
        res = self._post(confirmar_senha="senha_diferente123")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirmar_senha", res.data)

    def test_multiplos_erros_retornam_todos_os_campos(self):
        """Um payload completamente vazio deve listar todos os campos obrigatórios."""
        res = self.client.post(self.URL, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        for campo in ("razao_social", "cnpj", "username", "email", "senha"):
            self.assertIn(campo, res.data, f"Campo ausente nos erros: {campo}")
