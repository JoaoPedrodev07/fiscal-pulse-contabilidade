"""
Stress & failure tests — fiscal app.

Eleva o sistema a condições extremas: inputs maliciosos, limites de campo,
escalada de permissão, integridade referencial, idempotência e edge cases de API.

Rodar:
    python manage.py test fiscal.stress_tests --verbosity=2
"""
import datetime
import decimal
import io
import zipfile

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    Certificado, Cliente, ControleNSU, Documento, LogCaptura,
    StatusDocumento, TipoDocumento, Xml,
)

User = get_user_model()


def _staff(username="s_stress"):
    return User.objects.create_user(username=username, password="pass", is_staff=True)


def _operator(username="o_stress"):
    return User.objects.create_user(username=username, password="pass", is_staff=False)


def _cliente(**kw):
    d = {"cnpj": "12345678000195", "razao_social": "Stress Ltda"}
    d.update(kw)
    return Cliente.objects.create(**d)


def _doc(cliente, chave="35240112345678000195550010000000011234567890", **kw):
    d = {
        "tipo_documento": TipoDocumento.NFE,
        "emitente": "Emitente Stress",
        "valor": decimal.Decimal("100.00"),
        "data_emissao": datetime.date(2024, 1, 10),
        "competencia": "2024-01",
        "status": StatusDocumento.COMPLETO,
    }
    d.update(kw)
    return Documento.objects.create(cliente=cliente, chave=chave, **d)


# ──────────────────────────────────────────────────────────────────────────────
# 1. CAMPO CNPJ — LIMITES E FORMATOS INVÁLIDOS
# ──────────────────────────────────────────────────────────────────────────────

class CnpjFieldStressTest(APITestCase):
    """Testa o que a API aceita como CNPJ — gap crítico: sem validação de formato."""

    def setUp(self):
        self.staff = _staff("cnpj_staff")
        self.client.force_authenticate(user=self.staff)

    def tearDown(self):
        self.staff.delete()

    def _post(self, cnpj):
        return self.client.post("/api/clientes/", {"cnpj": cnpj, "razao_social": "X"}, format="json")

    def test_cnpj_13_digitos_rejeitado(self):
        """CNPJ com 13 dígitos deve ser rejeitado — campo exige 14 chars no modelo."""
        res = self._post("1234567890123")
        # Aceitável: 400 (validação) ou 201 (ausência de validação no serializer → BUG)
        if res.status_code == 201:
            self.fail(
                "VULNERABILIDADE: API aceita CNPJ com 13 dígitos. "
                "Falta validador de comprimento no ClienteSerializer."
            )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cnpj_15_digitos_rejeitado(self):
        """CNPJ com 15 dígitos deve ser rejeitado."""
        res = self._post("123456789012345")
        if res.status_code == 201:
            self.fail(
                "VULNERABILIDADE: API aceita CNPJ com 15 dígitos. "
                "Falta validador de comprimento no ClienteSerializer."
            )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cnpj_com_pontuacao_rejeitado(self):
        """CNPJ formatado (12.345.678/0001-95) deve ser rejeitado — modelo espera só dígitos."""
        res = self._post("12.345.678/0001-95")
        if res.status_code == 201:
            self.fail(
                "VULNERABILIDADE: API aceita CNPJ com pontuação. "
                "Falta validador de formato no ClienteSerializer."
            )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cnpj_vazio_rejeitado(self):
        res = self._post("")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cnpj_alfanumerico_rejeitado(self):
        """CNPJ com letras deve ser rejeitado."""
        res = self._post("1234567800AB95")
        if res.status_code == 201:
            self.fail("VULNERABILIDADE: API aceita CNPJ com letras.")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cnpj_sql_injection_rejeitado(self):
        res = self._post("'; DROP TABLE fiscal_cliente; --")
        self.assertIn(res.status_code, [400, 422])

    def test_cnpj_xss_rejeitado(self):
        res = self._post("<script>alert(1)</script>")
        self.assertIn(res.status_code, [400, 422])

    def test_cnpj_duplicado_rejeitado(self):
        self._post("12345678000195")
        res = self._post("12345678000195")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ──────────────────────────────────────────────────────────────────────────────
# 2. CAMPO CHAVE — IDEMPOTÊNCIA E UNICIDADE
# ──────────────────────────────────────────────────────────────────────────────

class ChaveUnicidadeStressTest(TestCase):
    """Garante que a chave de 44 dígitos não pode ser duplicada (idempotência da captura)."""

    def setUp(self):
        self.cliente = _cliente()
        self.chave = "35240112345678000195550010000000011234567890"

    def test_chave_duplicada_gera_integrity_error(self):
        _doc(self.cliente, chave=self.chave)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                _doc(self.cliente, chave=self.chave)

    def test_get_or_create_idempotente(self):
        """Simula o comportamento do worker de captura: get_or_create nunca duplica."""
        d1, created1 = Documento.objects.get_or_create(
            chave=self.chave,
            defaults={
                "cliente": self.cliente,
                "tipo_documento": TipoDocumento.NFE,
                "emitente": "X",
                "valor": decimal.Decimal("1.00"),
                "data_emissao": datetime.date.today(),
                "competencia": "2024-01",
                "status": StatusDocumento.CAPTURADO,
            },
        )
        d2, created2 = Documento.objects.get_or_create(
            chave=self.chave,
            defaults={
                "cliente": self.cliente,
                "tipo_documento": TipoDocumento.NFE,
                "emitente": "Y",
                "valor": decimal.Decimal("999.00"),
                "data_emissao": datetime.date.today(),
                "competencia": "2024-02",
                "status": StatusDocumento.COMPLETO,
            },
        )
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(d1.pk, d2.pk)
        self.assertEqual(d2.emitente, "X")  # first write wins

    def test_chave_44_chars_aceita(self):
        d = _doc(self.cliente, chave="A" * 44)
        self.assertIsNotNone(d.pk)

    def test_chave_vazia_nivel_db(self):
        """Chave vazia não tem restrição no modelo (blank não é proibido em CharField DB)."""
        # Este teste documenta o comportamento atual — se a chave vazia passar,
        # é uma lacuna (dois documentos "sem chave" colidiriam por UNIQUE).
        try:
            _doc(self.cliente, chave="")
            # Se chegou aqui, é uma lacuna: chave vazia é UNIQUE, então só um pode existir
            count = Documento.objects.filter(chave="").count()
            self.assertEqual(count, 1, "Uma chave vazia OK (única). Mas duas quebrariam.")
        except IntegrityError:
            pass  # também aceitável se o banco rejeitar


# ──────────────────────────────────────────────────────────────────────────────
# 3. COMPETÊNCIA — VALIDAÇÃO DE FORMATO
# ──────────────────────────────────────────────────────────────────────────────

class CompetenciaFormatStressTest(APITestCase):

    def setUp(self):
        self.staff = _staff("comp_staff")
        self.client.force_authenticate(user=self.staff)
        self.cliente = _cliente(cnpj="11111111000191", razao_social="Comp Test")

    def tearDown(self):
        Documento.objects.filter(cliente=self.cliente).delete()
        self.cliente.delete()
        self.staff.delete()

    def _post_doc(self, competencia):
        return self.client.post("/api/documentos/", {
            "cliente": self.cliente.pk,
            "chave": "C" * 44,
            "tipo_documento": "NFE",
            "emitente": "E",
            "valor": "100.00",
            "data_emissao": "2024-01-10",
            "competencia": competencia,
            "status": "CAPTURADO",
        }, format="json")

    def test_competencia_invalida_mes_13_rejeitada(self):
        # DocumentoViewSet é ReadOnly — POST deve retornar 405
        res = self._post_doc("2024-13")
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_competencia_formato_dd_mm_yyyy_rejeitada(self):
        res = self._post_doc("01-2024")
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_filtro_competencia_invalida_nao_quebra(self):
        """Filtrar por competência no formato errado não deve gerar 500."""
        res = self.client.get("/api/documentos/?competencia=INVALIDO")
        self.assertNotEqual(res.status_code, 500)

    def test_filtro_competencia_valida_retorna_200(self):
        _doc(self.cliente, chave="D" * 44, competencia="2024-01")
        res = self.client.get("/api/documentos/?competencia=2024-01")
        self.assertEqual(res.status_code, status.HTTP_200_OK)


# ──────────────────────────────────────────────────────────────────────────────
# 4. AUTENTICAÇÃO — BYPASS E TOKENS INVÁLIDOS
# ──────────────────────────────────────────────────────────────────────────────

class AuthBypassStressTest(APITestCase):

    ENDPOINTS = [
        "/api/clientes/",
        "/api/certificados/",
        "/api/documentos/",
        "/api/controles-nsu/",
        "/api/logs-captura/",
    ]

    def test_sem_token_todos_endpoints_retornam_401(self):
        for ep in self.ENDPOINTS:
            res = self.client.get(ep)
            self.assertEqual(
                res.status_code, status.HTTP_401_UNAUTHORIZED,
                f"{ep} aceitou request sem autenticação!"
            )

    def test_token_jwt_forjado_rejeitado(self):
        self.client.credentials(
            HTTP_AUTHORIZATION="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJ1c2VyX2lkIjoxfQ.forged_signature"
        )
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_scheme_errado_token_rejeitado(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token abc123")
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_bearer_vazio_rejeitado(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer ")
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_senha_errada_retorna_401(self):
        User.objects.create_user("auth_user", password="correct")
        res = self.client.post("/api/token/", {"username": "auth_user", "password": "wrong"})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("access", res.data)

    def test_login_usuario_inexistente_retorna_401(self):
        res = self.client.post("/api/token/", {"username": "naoexiste", "password": "x"})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token_forjado_rejeitado(self):
        res = self.client.post("/api/token/refresh/", {"refresh": "forged.token.here"})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_sem_corpo_retorna_400(self):
        res = self.client.post("/api/token/", {})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ──────────────────────────────────────────────────────────────────────────────
# 5. ESCALADA DE PERMISSÃO — OPERADOR vs STAFF
# ──────────────────────────────────────────────────────────────────────────────

class PermissionEscalationStressTest(APITestCase):

    def setUp(self):
        self.operator = _operator("perm_op")
        self.staff = _staff("perm_staff")
        self.cliente = _cliente(cnpj="22222222000191", razao_social="Perm Test")

    def tearDown(self):
        self.operator.delete()
        self.staff.delete()
        self.cliente.delete()

    def test_operador_nao_cria_cliente(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.post("/api/clientes/", {"cnpj": "33333333000191", "razao_social": "X"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_operador_nao_edita_cliente(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.patch(f"/api/clientes/{self.cliente.pk}/", {"razao_social": "Hack"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_operador_nao_deleta_cliente(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.delete(f"/api/clientes/{self.cliente.pk}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_operador_nao_cria_certificado(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.post("/api/certificados/", {
            "cliente": self.cliente.pk, "nome_arquivo": "hack.pfx",
            "validade": "2025-01-01", "ativo": True,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_operador_le_clientes(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_operador_le_documentos(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.get("/api/documentos/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_staff_cria_cliente(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.post("/api/clientes/", {"cnpj": "44444444000191", "razao_social": "OK"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_documentos_sao_readonly_para_staff(self):
        """Documentos são ReadOnly — staff não pode criar via API."""
        self.client.force_authenticate(user=self.staff)
        res = self.client.post("/api/documentos/", {
            "cliente": self.cliente.pk, "chave": "E" * 44,
            "tipo_documento": "NFE", "emitente": "E",
            "valor": "1.00", "data_emissao": "2024-01-01",
            "competencia": "2024-01", "status": "CAPTURADO",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


# ──────────────────────────────────────────────────────────────────────────────
# 6. INTEGRIDADE REFERENCIAL — CASCADE / PROTECT
# ──────────────────────────────────────────────────────────────────────────────

class IntegridadeReferencialStressTest(APITestCase):

    def setUp(self):
        self.staff = _staff("int_staff")
        self.client.force_authenticate(user=self.staff)

    def tearDown(self):
        self.staff.delete()

    def test_delete_cliente_com_certificado_bloqueado(self):
        """on_delete=PROTECT: não pode excluir cliente que tem certificado."""
        cli = _cliente(cnpj="55555555000191", razao_social="Prot1")
        Certificado.objects.create(
            cliente=cli, nome_arquivo="c.pfx",
            validade=datetime.date(2025, 1, 1), ativo=True,
        )
        res = self.client.delete(f"/api/clientes/{cli.pk}/")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)

    def test_delete_cliente_com_documento_bloqueado(self):
        """on_delete=PROTECT: não pode excluir cliente que tem documento."""
        cli = _cliente(cnpj="66666666000191", razao_social="Prot2")
        _doc(cli, chave="F" * 44)
        res = self.client.delete(f"/api/clientes/{cli.pk}/")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)

    def test_delete_cliente_sem_dependencias_ok(self):
        cli = _cliente(cnpj="77777777000191", razao_social="NoDeps")
        res = self.client.delete(f"/api/clientes/{cli.pk}/")
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def test_xml_cascade_deleta_com_documento(self):
        """Xml deve ser deletado em cascata quando o Documento é removido."""
        cli = _cliente(cnpj="88888888000191", razao_social="Casc")
        doc = _doc(cli, chave="G" * 44)
        xml = Xml.objects.create(documento=doc, conteudo="<xml/>")
        xml_pk = xml.pk
        doc.delete()
        self.assertFalse(Xml.objects.filter(pk=xml_pk).exists())

    def test_controle_nsu_cascade_deleta_com_cliente(self):
        cli = _cliente(cnpj="99999999000191", razao_social="NSUCasc")
        ControleNSU.objects.create(cliente=cli, tipo_documento="NFE", ultimo_nsu=100, max_nsu=500)
        cli_pk = cli.pk
        cli.delete()
        self.assertFalse(ControleNSU.objects.filter(cliente_id=cli_pk).exists())

    def test_nsu_unique_together_por_tipo(self):
        """Não pode ter dois ControleNSU do mesmo tipo para o mesmo cliente."""
        cli = _cliente(cnpj="10000000000191", razao_social="NSUUniq")
        ControleNSU.objects.create(cliente=cli, tipo_documento="NFE", ultimo_nsu=1, max_nsu=10)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ControleNSU.objects.create(cliente=cli, tipo_documento="NFE", ultimo_nsu=2, max_nsu=20)

    def test_certificado_sem_cliente_rejeitado_via_api(self):
        res = self.client.post("/api/certificados/", {
            "cliente": 999999, "nome_arquivo": "c.pfx",
            "validade": "2025-01-01", "ativo": True,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ──────────────────────────────────────────────────────────────────────────────
# 7. ENDPOINT XML E EXPORTAR_LOTE — EDGE CASES
# ──────────────────────────────────────────────────────────────────────────────

class XmlEndpointStressTest(APITestCase):

    def setUp(self):
        self.staff = _staff("xml_staff")
        self.client.force_authenticate(user=self.staff)
        self.cli = _cliente(cnpj="20000000000191", razao_social="XML Test")

    def tearDown(self):
        self.staff.delete()

    def test_xml_sem_xml_retorna_404(self):
        doc = _doc(self.cli, chave="H" * 44)
        res = self.client.get(f"/api/documentos/{doc.pk}/xml/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_xml_com_conteudo_retorna_application_xml(self):
        doc = _doc(self.cli, chave="I" * 44)
        Xml.objects.create(documento=doc, conteudo="<nfeProc><NFe/></nfeProc>")
        res = self.client.get(f"/api/documentos/{doc.pk}/xml/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("application/xml", res["Content-Type"])

    def test_xml_id_inexistente_retorna_404(self):
        res = self.client.get("/api/documentos/999999/xml/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_exportar_lote_sem_parametros_retorna_400(self):
        res = self.client.get("/api/documentos/exportar_lote/")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_exportar_lote_so_cliente_retorna_400(self):
        res = self.client.get(f"/api/documentos/exportar_lote/?cliente={self.cli.pk}")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_exportar_lote_so_competencia_retorna_400(self):
        res = self.client.get("/api/documentos/exportar_lote/?competencia=2024-01")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_exportar_lote_vazio_retorna_zip_valido(self):
        """Exportar sem documentos deve retornar ZIP vazio e válido, não erro."""
        res = self.client.get(
            f"/api/documentos/exportar_lote/?cliente={self.cli.pk}&competencia=2099-12"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            self.assertEqual(len(zf.namelist()), 0)

    def test_exportar_lote_docs_sem_xml_gera_zip_vazio(self):
        """Documentos sem XML no lote devem ser silenciosamente ignorados."""
        _doc(self.cli, chave="J" * 44, competencia="2024-06")
        res = self.client.get(
            f"/api/documentos/exportar_lote/?cliente={self.cli.pk}&competencia=2024-06"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            self.assertEqual(len(zf.namelist()), 0)

    def test_exportar_lote_com_xml_gera_zip_com_arquivos(self):
        doc = _doc(self.cli, chave="K" * 44, competencia="2024-07")
        Xml.objects.create(documento=doc, conteudo="<nfe/>")
        res = self.client.get(
            f"/api/documentos/exportar_lote/?cliente={self.cli.pk}&competencia=2024-07"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            self.assertEqual(len(zf.namelist()), 1)
            self.assertIn(f"{'K' * 44}.xml", zf.namelist())

    def test_exportar_lote_cliente_inexistente_retorna_zip_vazio(self):
        """Cliente_id inválido deve gerar ZIP vazio (queryset retorna 0 docs), não 404."""
        res = self.client.get("/api/documentos/exportar_lote/?cliente=999999&competencia=2024-01")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            self.assertEqual(len(zf.namelist()), 0)


# ──────────────────────────────────────────────────────────────────────────────
# 8. FILTROS E PAGINAÇÃO — INPUTS EXTREMOS
# ──────────────────────────────────────────────────────────────────────────────

class FiltrosPaginacaoStressTest(APITestCase):

    def setUp(self):
        self.op = _operator("filt_op")
        self.client.force_authenticate(user=self.op)
        self.cli = _cliente(cnpj="30000000000191", razao_social="Filtros Test")

    def tearDown(self):
        self.op.delete()

    def test_search_sql_injection_nao_quebra(self):
        res = self.client.get("/api/documentos/?search=' OR 1=1 --")
        self.assertNotEqual(res.status_code, 500)

    def test_search_muito_longo_nao_quebra(self):
        res = self.client.get(f"/api/documentos/?search={'X' * 5000}")
        self.assertNotEqual(res.status_code, 500)

    def test_filtro_tipo_invalido_nao_quebra(self):
        res = self.client.get("/api/documentos/?tipo_documento=INVALIDO")
        self.assertNotEqual(res.status_code, 500)

    def test_filtro_status_invalido_nao_quebra(self):
        res = self.client.get("/api/documentos/?status=LIXO")
        self.assertNotEqual(res.status_code, 500)

    def test_filtro_data_invalida_nao_quebra(self):
        res = self.client.get("/api/documentos/?data_emissao_inicio=nao-e-data")
        self.assertNotEqual(res.status_code, 500)

    def test_pagina_negativa_nao_quebra(self):
        res = self.client.get("/api/documentos/?page=-1")
        self.assertNotEqual(res.status_code, 500)

    def test_pagina_string_nao_quebra(self):
        res = self.client.get("/api/documentos/?page=abc")
        self.assertNotEqual(res.status_code, 500)

    def test_pagina_gigante_nao_quebra(self):
        res = self.client.get("/api/documentos/?page=99999999")
        self.assertNotEqual(res.status_code, 500)

    def test_cliente_id_negativo_nao_quebra(self):
        res = self.client.get("/api/documentos/?cliente=-1")
        self.assertNotEqual(res.status_code, 500)

    def test_cliente_id_string_nao_quebra(self):
        res = self.client.get("/api/documentos/?cliente=abc")
        self.assertNotEqual(res.status_code, 500)

    def test_detalhe_id_nao_existente_retorna_404(self):
        res = self.client.get("/api/documentos/999999999/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_detalhe_id_string_retorna_404(self):
        res = self.client.get("/api/documentos/abc/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


# ──────────────────────────────────────────────────────────────────────────────
# 9. PAYLOADS EXTREMOS
# ──────────────────────────────────────────────────────────────────────────────

class PayloadsExtremosStressTest(APITestCase):

    def setUp(self):
        self.staff = _staff("pay_staff")
        self.client.force_authenticate(user=self.staff)

    def tearDown(self):
        self.staff.delete()

    def test_razao_social_255_chars_aceita(self):
        res = self.client.post("/api/clientes/", {
            "cnpj": "31000000000191",
            "razao_social": "A" * 255,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_razao_social_256_chars_rejeitada(self):
        res = self.client.post("/api/clientes/", {
            "cnpj": "32000000000191",
            "razao_social": "A" * 256,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cliente_sem_razao_social_rejeitado(self):
        res = self.client.post("/api/clientes/", {"cnpj": "33000000000191"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_body_vazio_retorna_400(self):
        res = self.client.post("/api/clientes/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_body_nao_json_retorna_400_ou_415(self):
        res = self.client.post(
            "/api/clientes/",
            data="nao-e-json",
            content_type="application/json",
        )
        self.assertIn(res.status_code, [400, 415])

    def test_campos_extras_ignorados(self):
        """Campos não reconhecidos pelo serializer devem ser ignorados silenciosamente."""
        res = self.client.post("/api/clientes/", {
            "cnpj": "34000000000191",
            "razao_social": "Extra Fields",
            "campo_hacker": "injecao",
            "is_staff": True,
            "__class__": "exploit",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("campo_hacker", res.data)


# ──────────────────────────────────────────────────────────────────────────────
# 10. CONTROLE NSU — SEQUENCIALIDADE
# ──────────────────────────────────────────────────────────────────────────────

class ControleNSUStressTest(APITestCase):

    def setUp(self):
        self.staff = _staff("nsu_staff")
        self.client.force_authenticate(user=self.staff)
        self.cli = _cliente(cnpj="40000000000191", razao_social="NSU Test")

    def tearDown(self):
        self.staff.delete()

    def test_nsu_readonly_via_api(self):
        """ControleNSU é somente leitura na API."""
        res = self.client.post("/api/controles-nsu/", {
            "cliente": self.cli.pk, "tipo_documento": "NFE",
            "ultimo_nsu": 0, "max_nsu": 1000,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_nsu_tipos_validos(self):
        """Todos os tipos de documento devem poder ter um ControleNSU distinto."""
        for tipo in ["NFE", "CTE", "NFSE", "NFCE"]:
            ControleNSU.objects.get_or_create(
                cliente=self.cli, tipo_documento=tipo,
                defaults={"ultimo_nsu": 0, "max_nsu": 100},
            )
        res = self.client.get(f"/api/controles-nsu/?cliente={self.cli.pk}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_ultimo_nsu_maior_que_max_nsu_aceito_no_banco(self):
        """O banco não impede último > max — essa invariante deve ser garantida pela lógica do worker."""
        nsu = ControleNSU.objects.create(
            cliente=self.cli, tipo_documento="NFE",
            ultimo_nsu=999, max_nsu=100,
        )
        self.assertEqual(nsu.ultimo_nsu, 999)
        # Documenta que há lacuna: a API não valida a relação ultimo <= max

    def test_nsu_negativo_aceito_no_banco(self):
        """BigIntegerField não restringe valores negativos — lacuna de validação."""
        nsu = ControleNSU.objects.create(
            cliente=self.cli, tipo_documento="CTE",
            ultimo_nsu=-1, max_nsu=-100,
        )
        self.assertEqual(nsu.ultimo_nsu, -1)


# ──────────────────────────────────────────────────────────────────────────────
# 11. ISOLAMENTO DE DADOS — CLIENTE NÃO VÊ DADOS DE OUTRO
# ──────────────────────────────────────────────────────────────────────────────

class IsolamentoTenantStressTest(APITestCase):
    """
    ATENÇÃO: O sistema atual NÃO tem isolamento por tenant no ViewSet —
    qualquer usuário autenticado vê TODOS os documentos de TODOS os clientes.

    Este teste documenta o comportamento atual e serve como baseline
    para quando o isolamento for implementado.
    """

    def setUp(self):
        self.op1 = _operator("iso_op1")
        self.op2 = _operator("iso_op2")
        self.cli1 = _cliente(cnpj="50000000000191", razao_social="CLI 1")
        self.cli2 = _cliente(cnpj="51000000000191", razao_social="CLI 2")
        _doc(self.cli1, chave="L" * 44, competencia="2024-01")
        _doc(self.cli2, chave="M" * 44, competencia="2024-01")

    def tearDown(self):
        self.op1.delete()
        self.op2.delete()

    def test_operador_ve_documentos_de_todos_clientes_atualmente(self):
        """
        Comportamento ATUAL: operador 1 vê documentos do cliente 2.
        Quando o isolamento for implementado, este teste deve ser invertido
        (operador só vê documentos do seu cliente).
        """
        self.client.force_authenticate(user=self.op1)
        res = self.client.get("/api/documentos/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        chaves = [d["chave"] for d in res.data["results"]]
        # Documenta que ambas as chaves são visíveis — sem isolamento implementado
        self.assertIn("L" * 44, chaves)
        self.assertIn("M" * 44, chaves)
