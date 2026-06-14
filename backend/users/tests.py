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
