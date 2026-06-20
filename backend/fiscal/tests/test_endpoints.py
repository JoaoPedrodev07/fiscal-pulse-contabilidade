"""
Suíte de testes — app fiscal.

Cobre segurança, integridade de dados, idempotência e contratos de API
que devem estar sólidos antes da integração com os web services da SEFAZ.

Rodar:
    python manage.py test fiscal --verbosity=2
"""
import datetime
import decimal
import io
import zipfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from fiscal.models import (
    Certificado,
    Cliente,
    ControleNSU,
    Documento,
    LogCaptura,
    StatusDocumento,
    TipoDocumento,
    Xml,
)

User = get_user_model()


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_staff(username="admin", **kw):
    return User.objects.create_user(username=username, password="pass", is_staff=True, **kw)


def make_operator(username="operador", **kw):
    return User.objects.create_user(username=username, password="pass", is_staff=False, **kw)


def make_cliente(**kw):
    defaults = {"cnpj": "12345678000195", "razao_social": "Padaria do Joao Ltda", "telefone": "11999990001"}
    defaults.update(kw)
    return Cliente.objects.create(**defaults)


def make_certificado(cliente, dias=60, ativo=True):
    return Certificado.objects.create(
        cliente=cliente,
        nome_arquivo="cert.pfx",
        validade=datetime.date.today() + datetime.timedelta(days=dias),
        ativo=ativo,
    )


def make_documento(cliente, chave="35240112345678000195550010000000011234567890", **kw):
    defaults = {
        "tipo_documento": TipoDocumento.NFE,
        "emitente": "Fornecedor ABC Ltda",
        "valor": decimal.Decimal("1250.00"),
        "data_emissao": datetime.date(2024, 1, 10),
        "competencia": "2024-01",
        "status": StatusDocumento.COMPLETO,
    }
    defaults.update(kw)
    return Documento.objects.create(cliente=cliente, chave=chave, **defaults)


def make_nsu(cliente, tipo="NFE", ultimo=100, maximo=500):
    return ControleNSU.objects.create(
        cliente=cliente, tipo_documento=tipo, ultimo_nsu=ultimo, max_nsu=maximo
    )


def make_log(cliente, sucesso=True, tipo="NFE"):
    return LogCaptura.objects.create(
        cliente=cliente,
        tipo_documento=tipo,
        sucesso=sucesso,
        mensagem="OK" if sucesso else "Erro de conexao",
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. CLIENTES
# ──────────────────────────────────────────────────────────────────────────────

class ClienteEndpointTest(APITestCase):

    def setUp(self):
        self.staff = make_staff()
        self.operador = make_operator()
        self.cliente = make_cliente()

    def test_lista_clientes_staff(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_lista_clientes_operador(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_lista_clientes_sem_auth(self):
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cria_cliente_staff(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.post("/api/clientes/", {"cnpj": "98765432000110", "razao_social": "Distribuidora Silva SA"})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["cnpj"], "98765432000110")

    def test_cria_cliente_operador_proibido(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.post("/api/clientes/", {"cnpj": "11223344000180", "razao_social": "Tech ME"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cnpj_duplicado_retorna_400(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.post("/api/clientes/", {"cnpj": self.cliente.cnpj, "razao_social": "Clone"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deleta_cliente_sem_vinculos(self):
        c = make_cliente(cnpj="11111111000100", razao_social="Para deletar")
        self.client.force_authenticate(user=self.staff)
        res = self.client.delete(f"/api/clientes/{c.pk}/")
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def test_operador_nao_pode_deletar_cliente(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.delete(f"/api/clientes/{self.cliente.pk}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_lista_paginada(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/clientes/")
        self.assertIn("count", res.data)
        self.assertIn("results", res.data)

    def test_token_invalido_retorna_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer token-invalido")
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# ──────────────────────────────────────────────────────────────────────────────
# 2. INTEGRIDADE REFERENCIAL — PROTECT e CASCADE
# ──────────────────────────────────────────────────────────────────────────────

class IntegridadeReferencialTest(APITestCase):
    """
    Certificado e Documento usam on_delete=PROTECT.
    Deletar o Cliente enquanto ha vinculo deve ser bloqueado — garantia de
    auditoria fiscal: nao se apaga cliente com notas ou certificado ativo.
    """

    def setUp(self):
        self.staff = make_staff()
        self.cliente = make_cliente()
        self.client.force_authenticate(user=self.staff)

    def test_nao_pode_deletar_cliente_com_certificado(self):
        make_certificado(self.cliente)
        res = self.client.delete(f"/api/clientes/{self.cliente.pk}/")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Cliente.objects.filter(pk=self.cliente.pk).exists())

    def test_nao_pode_deletar_cliente_com_documento(self):
        make_documento(self.cliente)
        res = self.client.delete(f"/api/clientes/{self.cliente.pk}/")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Cliente.objects.filter(pk=self.cliente.pk).exists())

    def test_cascade_nsu_ao_deletar_cliente(self):
        """ControleNSU usa CASCADE — apagado junto com o cliente."""
        c = make_cliente(cnpj="22222222000100")
        make_nsu(c)
        pk = c.pk
        c.delete()
        self.assertEqual(ControleNSU.objects.filter(cliente_id=pk).count(), 0)

    def test_cascade_log_ao_deletar_cliente(self):
        """LogCaptura usa CASCADE — apagado junto com o cliente."""
        c = make_cliente(cnpj="33333333000100")
        make_log(c)
        pk = c.pk
        c.delete()
        self.assertEqual(LogCaptura.objects.filter(cliente_id=pk).count(), 0)


# ──────────────────────────────────────────────────────────────────────────────
# 3. IDEMPOTENCIA — UNIQUE na chave de acesso de 44 digitos
# ──────────────────────────────────────────────────────────────────────────────

class IdempotenciaDocumentoTest(TestCase):
    """
    Reexecucao da captura NUNCA duplica um Documento.
    O conector SEFAZ deve usar get_or_create(chave=...) como padrao.
    """

    def setUp(self):
        self.cliente = make_cliente()

    def test_chave_duplicada_lanca_integrityerror(self):
        from django.db import IntegrityError
        chave = "A" * 44
        make_documento(self.cliente, chave=chave)
        with self.assertRaises(IntegrityError):
            make_documento(self.cliente, chave=chave)

    def test_chave_unica_cross_cliente(self):
        """A UNIQUE e global — dois clientes nao podem ter a mesma chave."""
        from django.db import IntegrityError
        outro = make_cliente(cnpj="44444444000100")
        chave = "B" * 44
        make_documento(self.cliente, chave=chave)
        with self.assertRaises(IntegrityError):
            make_documento(outro, chave=chave)

    def test_chaves_distintas_coexistem(self):
        make_documento(self.cliente, chave="1" * 44)
        make_documento(self.cliente, chave="2" * 44)
        self.assertEqual(Documento.objects.filter(cliente=self.cliente).count(), 2)

    def test_get_or_create_pattern_idempotente(self):
        """Simula o padrao que o conector SEFAZ deve adotar."""
        chave = "C" * 44
        base = dict(
            cliente=self.cliente, tipo_documento="NFE",
            emitente="E", valor="100.00",
            data_emissao="2024-01-01", competencia="2024-01",
        )
        doc1, criado1 = Documento.objects.get_or_create(chave=chave, defaults=base)
        doc2, criado2 = Documento.objects.get_or_create(
            chave=chave, defaults={**base, "valor": "999.00"}
        )
        self.assertTrue(criado1)
        self.assertFalse(criado2)
        self.assertEqual(doc1.pk, doc2.pk)
        self.assertEqual(Documento.objects.filter(chave=chave).count(), 1)
        # Valor original preservado — nao sobrescrito na segunda chamada
        self.assertEqual(doc2.valor, decimal.Decimal("100.00"))


# ──────────────────────────────────────────────────────────────────────────────
# 4. CONTROLE DE NSU
# ──────────────────────────────────────────────────────────────────────────────

class ControleNSUTest(APITestCase):
    """
    unique_together = [["cliente", "tipo_documento"]] garante que nao haja dois
    contadores para o mesmo par — desordem de NSU causa "Consumo Indevido" na SEFAZ.
    """

    def setUp(self):
        self.staff = make_staff()
        self.operador = make_operator()
        self.cliente = make_cliente()

    def test_unique_together_impede_duplicata(self):
        from django.db import IntegrityError
        make_nsu(self.cliente, tipo="NFE")
        with self.assertRaises(IntegrityError):
            make_nsu(self.cliente, tipo="NFE")

    def test_tipos_distintos_para_mesmo_cliente_permitidos(self):
        make_nsu(self.cliente, tipo="NFE")
        make_nsu(self.cliente, tipo="CTE")
        make_nsu(self.cliente, tipo="NFSE")
        self.assertEqual(ControleNSU.objects.filter(cliente=self.cliente).count(), 3)

    def test_mesmo_tipo_clientes_distintos_permitidos(self):
        outro = make_cliente(cnpj="55555555000100")
        make_nsu(self.cliente, tipo="NFE")
        make_nsu(outro, tipo="NFE")
        self.assertEqual(ControleNSU.objects.filter(tipo_documento="NFE").count(), 2)

    def test_sem_auth_retorna_401(self):
        res = self.client.get("/api/controles-nsu/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_operador_pode_listar(self):
        make_nsu(self.cliente)
        self.client.force_authenticate(user=self.operador)
        res = self.client.get("/api/controles-nsu/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_lista_paginada_com_results(self):
        make_nsu(self.cliente)
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/controles-nsu/")
        self.assertIn("count", res.data)
        self.assertIn("results", res.data)

    def test_serializer_inclui_cliente_nome(self):
        make_nsu(self.cliente)
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/controles-nsu/")
        item = res.data["results"][0]
        self.assertIn("cliente_nome", item)
        self.assertEqual(item["cliente_nome"], self.cliente.razao_social)

    def test_valores_ultimo_e_max_nsu(self):
        make_nsu(self.cliente, ultimo=200, maximo=1000)
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/controles-nsu/")
        item = res.data["results"][0]
        self.assertEqual(item["ultimo_nsu"], 200)
        self.assertEqual(item["max_nsu"], 1000)


# ──────────────────────────────────────────────────────────────────────────────
# 5. LOG DE CAPTURA
# ──────────────────────────────────────────────────────────────────────────────

class LogCapturaTest(APITestCase):

    def setUp(self):
        self.staff = make_staff()
        self.operador = make_operator()
        self.cliente = make_cliente()

    def test_sem_auth_retorna_401(self):
        res = self.client.get("/api/logs-captura/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_lista_paginada_com_results(self):
        make_log(self.cliente)
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/logs-captura/")
        self.assertIn("count", res.data)
        self.assertIn("results", res.data)

    def test_serializer_inclui_cliente_nome(self):
        make_log(self.cliente, sucesso=True)
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/logs-captura/")
        item = res.data["results"][0]
        self.assertIn("cliente_nome", item)
        self.assertEqual(item["cliente_nome"], self.cliente.razao_social)

    def test_serializer_inclui_fk_e_nome(self):
        """Frontend usa cliente (id) para links e cliente_nome para exibicao."""
        make_log(self.cliente)
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/logs-captura/")
        item = res.data["results"][0]
        self.assertIn("cliente", item)
        self.assertIn("cliente_nome", item)
        self.assertEqual(item["cliente"], self.cliente.pk)

    def test_sucesso_e_erro_representados(self):
        make_log(self.cliente, sucesso=True)
        make_log(self.cliente, sucesso=False)
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/logs-captura/")
        resultados = res.data["results"]
        self.assertEqual(len([r for r in resultados if r["sucesso"]]), 1)
        self.assertEqual(len([r for r in resultados if not r["sucesso"]]), 1)

    def test_operador_pode_listar(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.get("/api/logs-captura/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)


# ──────────────────────────────────────────────────────────────────────────────
# 6. CERTIFICADOS
# ──────────────────────────────────────────────────────────────────────────────

class CertificadoEndpointTest(APITestCase):

    def setUp(self):
        self.staff = make_staff()
        self.operador = make_operator()
        self.cliente = make_cliente()
        Certificado.objects.create(
            cliente=self.cliente,
            nome_arquivo="cert.pfx",
            validade=datetime.date(2026, 12, 31),
        )

    def test_lista_staff(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/certificados/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_lista_operador(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.get("/api/certificados/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_sem_auth_retorna_401(self):
        res = self.client.get("/api/certificados/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_criar_staff(self):
        import datetime as dt
        import os
        from unittest.mock import patch
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs12 as pkcs12_mod
        from cryptography.fernet import Fernet

        senha = b"teste123"
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(nome)
            .issuer_name(nome)
            .public_key(priv.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(dt.datetime.now(dt.timezone.utc))
            .not_valid_after(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365))
            .sign(priv, hashes.SHA256())
        )
        pfx_bytes = pkcs12_mod.serialize_key_and_certificates(
            name=b"test", key=priv, cert=cert, cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(senha),
        )

        test_key = Fernet.generate_key().decode()
        self.client.force_authenticate(user=self.staff)
        with patch.dict(os.environ, {"CERT_ENCRYPTION_KEY": test_key}):
            res = self.client.post(
                "/api/certificados/",
                {"cliente": self.cliente.pk, "arquivo": io.BytesIO(pfx_bytes), "senha": senha.decode()},
                format="multipart",
            )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_criar_operador_proibido(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.post(
            "/api/certificados/",
            {"cliente": self.cliente.pk, "nome_arquivo": "novo.pfx", "validade": "2027-12-31"},
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_resposta_inclui_cliente_nome(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/certificados/")
        item = res.data["results"][0]
        self.assertIn("cliente_nome", item)
        self.assertEqual(item["cliente_nome"], self.cliente.razao_social)

    def test_resposta_nao_expoe_senha(self):
        """A senha do certificado A1 jamais deve aparecer na API."""
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/certificados/")
        item = res.data["results"][0]
        self.assertNotIn("senha", item)
        self.assertNotIn("password", item)

    def test_resposta_inclui_validade_e_ativo(self):
        """Frontend usa esses campos para calcular badges de vencimento."""
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/certificados/")
        item = res.data["results"][0]
        self.assertIn("validade", item)
        self.assertIn("ativo", item)

    def test_lista_paginada(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/certificados/")
        self.assertIn("count", res.data)
        self.assertIn("results", res.data)


# ──────────────────────────────────────────────────────────────────────────────
# 7. THRESHOLDS DE VENCIMENTO (camada de dados para o frontend)
# ──────────────────────────────────────────────────────────────────────────────

class CertificadoVencimentoTest(TestCase):
    """
    O frontend exibe badges coloridos com base em (validade - hoje).
    >30 d -> Ativo  |  7-30 d -> Vence em breve  |  <7 d ou vencido -> Critico/Vencido.
    """

    def setUp(self):
        self.cliente = make_cliente()

    def _dias(self, cert):
        return (cert.validade - datetime.date.today()).days

    def test_ativo_mais_30_dias(self):
        cert = make_certificado(self.cliente, dias=60)
        self.assertGreater(self._dias(cert), 30)
        self.assertTrue(cert.ativo)

    def test_vence_em_breve_entre_7_e_30(self):
        cert = make_certificado(self.cliente, dias=15)
        d = self._dias(cert)
        self.assertGreater(d, 7)
        self.assertLessEqual(d, 30)

    def test_critico_menos_7_dias(self):
        cert = make_certificado(self.cliente, dias=4)
        d = self._dias(cert)
        self.assertGreater(d, 0)
        self.assertLessEqual(d, 7)

    def test_vencido_passado(self):
        cert = make_certificado(self.cliente, dias=-1)
        self.assertLessEqual(self._dias(cert), 0)

    def test_inativo_com_validade_futura(self):
        """ativo=False com validade futura — frontend trata como Vencido."""
        cert = make_certificado(self.cliente, dias=60, ativo=False)
        self.assertFalse(cert.ativo)
        self.assertGreater(self._dias(cert), 0)


# ──────────────────────────────────────────────────────────────────────────────
# 8. DOCUMENTOS — filtros e paginacao
# ──────────────────────────────────────────────────────────────────────────────

class DocumentoEndpointTest(APITestCase):

    def setUp(self):
        self.staff = make_staff()
        self.operador = make_operator()
        self.cliente = make_cliente()
        self.doc = make_documento(self.cliente)
        Xml.objects.create(documento=self.doc, conteudo="<xml>teste</xml>")

    def test_listar_autenticado_retorna_200(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("results", res.data)

    def test_listar_operador_ve_todos_clientes(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.get("/api/documentos/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

    def test_listar_sem_autenticacao_retorna_401(self):
        res = self.client.get("/api/documentos/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_download_xml_retorna_application_xml(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/{self.doc.pk}/xml/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("application/xml", res["Content-Type"])

    def test_download_xml_sem_xml_retorna_404(self):
        doc_sem_xml = make_documento(self.cliente, chave="35240999999999999999550010000000991234567899")
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/{doc_sem_xml.pk}/xml/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_xml_sem_auth_retorna_401(self):
        res = self.client.get(f"/api/documentos/{self.doc.pk}/xml/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_conteudo_xml_correto(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/{self.doc.pk}/xml/")
        self.assertIn(b"<xml>", res.content)

    def test_filtro_por_competencia(self):
        make_documento(
            self.cliente,
            chave="35240212345678000195550010000000021234567891",
            competencia="2024-02",
        )
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/?competencia=2024-01")
        self.assertEqual(res.data["count"], 1)

    def test_filtro_por_cliente(self):
        outro = make_cliente(cnpj="98765432000110", razao_social="Outro Ltda")
        make_documento(outro, chave="35240312345678000110550010000000031234567892")
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/?cliente={self.cliente.pk}")
        self.assertEqual(res.data["count"], 1)

    def test_filtro_por_tipo_documento(self):
        make_documento(
            self.cliente,
            chave="35240412345678000195550010000000041234567893",
            tipo_documento=TipoDocumento.CTE,
        )
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/?tipo_documento=CTE")
        self.assertEqual(res.data["count"], 1)

    def test_filtro_por_status(self):
        make_documento(
            self.cliente,
            chave="35240512345678000195550010000000051234567894",
            status=StatusDocumento.CAPTURADO,
        )
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/?status=CAPTURADO")
        self.assertEqual(res.data["count"], 1)

    def test_filtro_data_inicio(self):
        make_documento(
            self.cliente,
            chave="35240612345678000195550010000000061234567895",
            data_emissao=datetime.date(2024, 3, 1),
            competencia="2024-03",
        )
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/?data_emissao_inicio=2024-03-01")
        self.assertEqual(res.data["count"], 1)

    def test_filtro_data_fim(self):
        make_documento(
            self.cliente,
            chave="35240712345678000195550010000000071234567896",
            data_emissao=datetime.date(2024, 3, 1),
            competencia="2024-03",
        )
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/?data_emissao_fim=2024-01-31")
        self.assertEqual(res.data["count"], 1)

    def test_search_por_emitente(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/?search=Fornecedor")
        self.assertEqual(res.data["count"], 1)

    def test_serializer_inclui_cliente_nome(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/")
        item = res.data["results"][0]
        self.assertIn("cliente_nome", item)
        self.assertEqual(item["cliente_nome"], self.cliente.razao_social)

    def test_detalhe_inclui_xml_aninhado(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/{self.doc.pk}/")
        self.assertIn("xml", res.data)
        self.assertIn("conteudo", res.data["xml"])


# ──────────────────────────────────────────────────────────────────────────────
# 9. EXPORTAR LOTE
# ──────────────────────────────────────────────────────────────────────────────

class ExportarLoteTest(APITestCase):

    def setUp(self):
        self.staff = make_staff()
        self.cliente = make_cliente()
        doc = make_documento(self.cliente)
        Xml.objects.create(documento=doc, conteudo="<nfeProc><NFe>xml-de-teste</NFe></nfeProc>")

    def test_sem_query_params_retorna_400(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/exportar_lote/")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sem_competencia_retorna_400(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/exportar_lote/?cliente={self.cliente.pk}")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sem_cliente_retorna_400(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/exportar_lote/?competencia=2024-01")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_com_params_retorna_zip(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(
            f"/api/documentos/exportar_lote/?cliente={self.cliente.pk}&competencia=2024-01"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "application/zip")

    def test_zip_contem_um_arquivo_xml(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(
            f"/api/documentos/exportar_lote/?cliente={self.cliente.pk}&competencia=2024-01"
        )
        zf = zipfile.ZipFile(io.BytesIO(res.content))
        self.assertEqual(len(zf.namelist()), 1)
        self.assertTrue(zf.namelist()[0].endswith(".xml"))

    def test_conteudo_xml_no_zip_correto(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(
            f"/api/documentos/exportar_lote/?cliente={self.cliente.pk}&competencia=2024-01"
        )
        zf = zipfile.ZipFile(io.BytesIO(res.content))
        conteudo = zf.read(zf.namelist()[0]).decode()
        self.assertIn("nfeProc", conteudo)

    def test_competencia_sem_documentos_retorna_zip_vazio(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(
            f"/api/documentos/exportar_lote/?cliente={self.cliente.pk}&competencia=2099-12"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        zf = zipfile.ZipFile(io.BytesIO(res.content))
        self.assertEqual(len(zf.namelist()), 0)

    def test_sem_auth_retorna_401(self):
        res = self.client.get(
            f"/api/documentos/exportar_lote/?cliente={self.cliente.pk}&competencia=2024-01"
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# ──────────────────────────────────────────────────────────────────────────────
# 10. VALIDACAO DE SERIALIZER
# ──────────────────────────────────────────────────────────────────────────────

class ValidacaoCompetenciaTest(APITestCase):

    def test_competencia_formato_invalido(self):
        from fiscal.serializers import DocumentoSerializer
        s = DocumentoSerializer(data={
            "cliente": 1,
            "chave": "35240112345678000195550010000000011234567890",
            "tipo_documento": "NFE",
            "emitente": "X",
            "valor": "100.00",
            "data_emissao": "2024-01-10",
            "competencia": "01-2024",
            "status": "CAPTURADO",
        })
        s.is_valid()
        self.assertIn("competencia", s.errors)

    def test_competencia_formato_correto_valido(self):
        from fiscal.serializers import DocumentoSerializer
        s = DocumentoSerializer(data={
            "cliente": 1,
            "chave": "35240112345678000195550010000000011234567890",
            "tipo_documento": "NFE",
            "emitente": "X",
            "valor": "100.00",
            "data_emissao": "2024-01-10",
            "competencia": "2024-01",
            "status": "CAPTURADO",
        })
        s.is_valid()
        self.assertNotIn("competencia", s.errors)

    def test_competencia_mes_13_invalido(self):
        from fiscal.serializers import DocumentoSerializer
        s = DocumentoSerializer(data={
            "cliente": 1,
            "chave": "35240112345678000195550010000000011234567890",
            "tipo_documento": "NFE",
            "emitente": "X",
            "valor": "100.00",
            "data_emissao": "2024-01-10",
            "competencia": "2024-13",
            "status": "CAPTURADO",
        })
        s.is_valid()
        self.assertIn("competencia", s.errors)


# ──────────────────────────────────────────────────────────────────────────────
# 11. AUTENTICACAO JWT — fluxo completo
# ──────────────────────────────────────────────────────────────────────────────

class JWTFluxoTest(APITestCase):

    def setUp(self):
        self.user = make_staff(username="jwt_user")

    def test_login_retorna_access_e_refresh(self):
        res = self.client.post("/api/token/", {"username": "jwt_user", "password": "pass"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)

    def test_credencial_errada_retorna_401(self):
        res = self.client.post("/api/token/", {"username": "jwt_user", "password": "errada"})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_access_token_permite_acesso(self):
        res = self.client.post("/api/token/", {"username": "jwt_user", "password": "pass"})
        token = res.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        res2 = self.client.get("/api/clientes/")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)

    def test_token_invalido_retorna_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer nao.e.um.token.valido")
        res = self.client.get("/api/clientes/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_gera_novo_access(self):
        res = self.client.post("/api/token/", {"username": "jwt_user", "password": "pass"})
        refresh = res.data["refresh"]
        res2 = self.client.post("/api/token/refresh/", {"refresh": refresh})
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertIn("access", res2.data)

    def test_refresh_invalido_retorna_401(self):
        res = self.client.post("/api/token/refresh/", {"refresh": "token-falso"})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# ──────────────────────────────────────────────────────────────────────────────
# 12. ENDPOINT RECONCILIAR
# ──────────────────────────────────────────────────────────────────────────────

class ReconciliarEndpointTest(APITestCase):
    """
    GET /api/documentos/reconciliar/?cliente=<id>
    Relatório de consistência: capturados vs. maxNSU disponível.
    Permite ao contador verificar gaps antes do fechamento fiscal.
    """

    def setUp(self):
        self.staff = make_staff(username="staff_rec")
        self.operador = make_operator(username="op_rec")
        self.cliente = make_cliente(cnpj="91234567000100", razao_social="Reconciliar LTDA")
        self.nsu = make_nsu(self.cliente, tipo="NFE", ultimo=80, maximo=100)
        self.doc = make_documento(self.cliente, chave="R" * 44)

    def test_sem_auth_retorna_401(self):
        res = self.client.get(f"/api/documentos/reconciliar/?cliente={self.cliente.pk}")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retorna_200_autenticado(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/reconciliar/?cliente={self.cliente.pk}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_operador_pode_acessar(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.get(f"/api/documentos/reconciliar/?cliente={self.cliente.pk}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_campos_obrigatorios_presentes(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/reconciliar/?cliente={self.cliente.pk}")
        item = res.data[0]
        for campo in ("cliente", "cliente_nome", "tipo_documento", "ultimo_nsu",
                       "max_nsu", "capturados", "gap", "atualizado_em"):
            self.assertIn(campo, item, f"Campo ausente na resposta: {campo}")

    def test_gap_calculado_corretamente(self):
        """gap = max_nsu - ultimo_nsu quando max > ultimo."""
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/reconciliar/?cliente={self.cliente.pk}")
        item = res.data[0]
        self.assertEqual(item["ultimo_nsu"], 80)
        self.assertEqual(item["max_nsu"], 100)
        self.assertEqual(item["gap"], 20)

    def test_capturados_reflete_documentos_reais(self):
        """capturados deve contar exatamente os Documentos salvos no banco."""
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/reconciliar/?cliente={self.cliente.pk}")
        item = res.data[0]
        self.assertEqual(item["capturados"], 1)

    def test_gap_zero_quando_sincronizado(self):
        self.nsu.ultimo_nsu = 100
        self.nsu.save()
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/reconciliar/?cliente={self.cliente.pk}")
        item = res.data[0]
        self.assertEqual(item["gap"], 0)

    def test_sem_filtro_cliente_retorna_todos(self):
        outro = make_cliente(cnpj="81234567000100", razao_social="Outro LTDA")
        make_nsu(outro, tipo="CTE", ultimo=10, maximo=50)
        self.client.force_authenticate(user=self.staff)
        res = self.client.get("/api/documentos/reconciliar/")
        self.assertGreaterEqual(len(res.data), 2)

    def test_cliente_nome_no_resultado(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(f"/api/documentos/reconciliar/?cliente={self.cliente.pk}")
        self.assertEqual(res.data[0]["cliente_nome"], self.cliente.razao_social)


# ──────────────────────────────────────────────────────────────────────────────
# 13. ENDPOINT CAPTURAR NFS-e DIRETA
# ──────────────────────────────────────────────────────────────────────────────

class CapturarNfseDiretaEndpointTest(APITestCase):
    """
    POST /api/clientes/{id}/capturar-nfse/
    Fallback cirúrgico: busca NFS-e por Chave de Acesso (44 dígitos).
    NUNCA chama SEFAZ real — tudo mockado.
    """

    CHAVE_VALIDA = "35260612345678000199550010000000010000000001"

    def setUp(self):
        self.staff = make_staff(username="staff_nfse")
        self.operador = make_operator(username="op_nfse")
        self.cliente = make_cliente(cnpj="71234567000100", razao_social="NFS-e Direta LTDA")
        cert = Certificado.objects.create(
            cliente=self.cliente,
            nome_arquivo="cert.pfx",
            validade=datetime.date(2027, 12, 31),
            ativo=True,
        )
        cert.conteudo_criptografado = b"pfx-fake"
        cert.senha_criptografada = b"senha-fake"
        cert.save()

    def _url(self):
        return f"/api/clientes/{self.cliente.pk}/capturar-nfse/"

    def _patch_chain(self, resultado_str="SUCESSO"):
        from unittest.mock import MagicMock, patch
        mock_svc = MagicMock()
        mock_svc.capturar_por_chave_direta.return_value = resultado_str
        return [
            patch("fiscal.services.cofre.decrypt_a1", return_value=b"senha-decifrada"),
            patch("fiscal.conectores.fabrica.inicializar_cliente_sefaz", return_value=MagicMock()),
            patch("fiscal.conectores.nfse.NFSeADNCapturaService", return_value=mock_svc),
        ]

    def _with_patches(self, resultado_str="SUCESSO"):
        from contextlib import ExitStack
        stack = ExitStack()
        for p in self._patch_chain(resultado_str):
            stack.enter_context(p)
        return stack

    def test_sem_auth_retorna_401(self):
        res = self.client.post(self._url(), {"chave_acesso": self.CHAVE_VALIDA})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_operador_proibido_retorna_403(self):
        self.client.force_authenticate(user=self.operador)
        res = self.client.post(self._url(), {"chave_acesso": self.CHAVE_VALIDA})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_chave_com_menos_de_44_digitos_retorna_400(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.post(self._url(), {"chave_acesso": "123"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_chave_com_mais_de_44_digitos_retorna_400(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.post(self._url(), {"chave_acesso": "1" * 45})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cliente_sem_certificado_retorna_422(self):
        cliente_sem_cert = make_cliente(cnpj="61234567000100", razao_social="Sem Cert LTDA")
        self.client.force_authenticate(user=self.staff)
        res = self.client.post(
            f"/api/clientes/{cliente_sem_cert.pk}/capturar-nfse/",
            {"chave_acesso": self.CHAVE_VALIDA},
        )
        self.assertEqual(res.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_sucesso_retorna_200(self):
        self.client.force_authenticate(user=self.staff)
        with self._with_patches("SUCESSO"):
            res = self.client.post(self._url(), {"chave_acesso": self.CHAVE_VALIDA})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["sucesso"])

    def test_nota_nao_encontrada_retorna_502(self):
        self.client.force_authenticate(user=self.staff)
        with self._with_patches("NOTA_NAO_ENCONTRADA"):
            res = self.client.post(self._url(), {"chave_acesso": self.CHAVE_VALIDA})
        self.assertEqual(res.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(res.data["sucesso"])

    def test_erro_conexao_retorna_502(self):
        self.client.force_authenticate(user=self.staff)
        with self._with_patches("ERRO_CONEXAO"):
            res = self.client.post(self._url(), {"chave_acesso": self.CHAVE_VALIDA})
        self.assertEqual(res.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_resposta_contem_mensagem(self):
        self.client.force_authenticate(user=self.staff)
        with self._with_patches("SUCESSO"):
            res = self.client.post(self._url(), {"chave_acesso": self.CHAVE_VALIDA})
        self.assertIn("mensagem", res.data)

    def test_excecao_no_conector_retorna_502(self):
        from unittest.mock import patch
        self.client.force_authenticate(user=self.staff)
        with patch("fiscal.services.cofre.decrypt_a1", side_effect=RuntimeError("Fernet key inválida")):
            res = self.client.post(self._url(), {"chave_acesso": self.CHAVE_VALIDA})
        self.assertEqual(res.status_code, status.HTTP_502_BAD_GATEWAY)
