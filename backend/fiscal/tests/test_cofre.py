"""
TDD — Cofre de Certificados A1
Escrito ANTES da implementação em fiscal/services/cofre.py.

Regras invariantes testadas:
  1. Roundtrip: decrypt(encrypt(x)) == x
  2. Não-determinismo: Fernet usa IV+timestamp, mesmo input → ciphertext diferente
  3. Chave errada → InvalidToken (não retorna lixo silenciosamente)
  4. Chave ausente no ambiente → KeyError imediato (fail fast)
"""
import os
from unittest.mock import patch

from cryptography.fernet import Fernet, InvalidToken
from django.test import SimpleTestCase

# Chave válida para uso nos testes — gerada uma vez, reutilizada por fixture
_TEST_KEY = Fernet.generate_key().decode()


class CofreRoundtripTest(SimpleTestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {"CERT_ENCRYPTION_KEY": _TEST_KEY})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    def test_roundtrip_basico(self):
        """decrypt(encrypt(x)) deve retornar exatamente x."""
        from fiscal.services.cofre import decrypt_a1, encrypt_a1

        data = b"\x30\x82\x04pfx-simulado\x00\xff"
        self.assertEqual(decrypt_a1(encrypt_a1(data)), data)

    def test_roundtrip_vazio(self):
        """Entrada vazia também sobrevive ao roundtrip."""
        from fiscal.services.cofre import decrypt_a1, encrypt_a1

        self.assertEqual(decrypt_a1(encrypt_a1(b"")), b"")

    def test_encrypt_nao_deterministico(self):
        """Fernet usa IV+timestamp: mesmo input deve gerar ciphertexts distintos."""
        from fiscal.services.cofre import encrypt_a1

        data = b"certificado-a1-bytes"
        ct1 = encrypt_a1(data)
        ct2 = encrypt_a1(data)
        self.assertNotEqual(ct1, ct2, "encrypt_a1 não deve ser determinístico")

    def test_ciphertext_nao_contem_plaintext(self):
        """O ciphertext não pode expor o conteúdo original em nenhum ponto."""
        from fiscal.services.cofre import encrypt_a1

        data = b"segredo-pfx"
        ct = encrypt_a1(data)
        self.assertNotIn(data, ct)

    def test_chave_errada_levanta_invalid_token(self):
        """decrypt com chave diferente deve levantar InvalidToken, nunca retornar lixo."""
        from fiscal.services.cofre import decrypt_a1, encrypt_a1

        ct = encrypt_a1(b"bytes do pfx")
        chave_errada = Fernet.generate_key().decode()

        with patch.dict(os.environ, {"CERT_ENCRYPTION_KEY": chave_errada}):
            with self.assertRaises(InvalidToken):
                decrypt_a1(ct)

    def test_chave_ausente_levanta_key_error(self):
        """Sem CERT_ENCRYPTION_KEY no ambiente, deve falhar imediatamente (fail fast)."""
        from fiscal.services.cofre import encrypt_a1

        env_sem_chave = {k: v for k, v in os.environ.items() if k != "CERT_ENCRYPTION_KEY"}
        with patch.dict(os.environ, env_sem_chave, clear=True):
            with self.assertRaises(KeyError):
                encrypt_a1(b"qualquer dado")
