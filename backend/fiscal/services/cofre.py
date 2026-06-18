"""
Cofre de Certificados A1.

Única responsabilidade: criptografar e descriptografar o binário .pfx em repouso.
Usa Fernet (AES-128-CBC + HMAC-SHA256) da biblioteca `cryptography`.

Invariantes de segurança:
- A chave NUNCA é logada, cacheada em módulo ou exposta pela API.
- O plaintext (pfx_bytes) NUNCA é retornado por endpoints.
- _key() lê os.environ em cada chamada — sem cache de módulo.
"""
import os

from cryptography.fernet import Fernet


def _key() -> bytes:
    """
    Lê CERT_ENCRYPTION_KEY do ambiente.
    Fernet exige chave de 32 bytes codificada em URL-safe base64 (44 chars).
    Levanta KeyError se a variável estiver ausente — fail fast intencional.
    """
    return os.environ["CERT_ENCRYPTION_KEY"].encode()


def encrypt_a1(pfx_bytes: bytes) -> bytes:
    """Criptografa o binário do certificado. Retorna token Fernet (bytes)."""
    return Fernet(_key()).encrypt(pfx_bytes)


def decrypt_a1(ciphertext: bytes) -> bytes:
    """
    Descriptografa o token Fernet. Retorna o pfx_bytes original.
    Levanta cryptography.fernet.InvalidToken se a chave for incorreta
    ou o token estiver corrompido.
    """
    return Fernet(_key()).decrypt(ciphertext)
