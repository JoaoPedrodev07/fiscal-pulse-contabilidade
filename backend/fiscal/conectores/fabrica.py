"""
Fábrica de conectores SEFAZ.

Comunicação fiscal usa apenas requests + cryptography:
- NFS-e: REST mTLS via ADN (requests)
- NF-e / CT-e: SOAP ainda não implementado sem pynfe
"""
import logging
import os
import tempfile

from fiscal.models import Certificado as CertificadoModel
from fiscal.services.cofre import decrypt_a1

logger = logging.getLogger(__name__)

_UF_CODIGO = {
    'ac': 12, 'al': 27, 'ap': 16, 'am': 13, 'ba': 29, 'ce': 23,
    'df': 53, 'es': 32, 'go': 52, 'ma': 21, 'mt': 51, 'ms': 50,
    'mg': 31, 'pa': 15, 'pb': 25, 'pr': 41, 'pe': 26, 'pi': 22,
    'rj': 33, 'rn': 24, 'rs': 43, 'ro': 11, 'rr': 14, 'sc': 42,
    'sp': 35, 'se': 28, 'to': 17,
}


class _RespostaAdapter:
    """Interface .status_code/.text compatível com NFeCapturaService."""
    status_code = 200

    def __init__(self, texto: str):
        self.text = texto


class ConectorSefaz:
    """
    Adapter que mantém o PFX descriptografado em RAM e expõe os métodos
    de consulta usados pelos serviços de captura.

    O PFX é gravado em disco APENAS durante chamadas REST (PEM temporário)
    e deletado imediatamente no bloco finally.
    """

    def __init__(self, pfx_bytes: bytes, senha: str, uf: str, codigo_uf: int, homologacao: bool):
        self._pfx_bytes = pfx_bytes
        self._senha = senha
        self._uf = uf
        self._codigo_uf = codigo_uf
        self._homologacao = homologacao

    # ── NF-e ────────────────────────────────────────────────────────────────

    def consulta_notas_cnpj(self, cnpj: str, nsu: int) -> _RespostaAdapter:
        """distNSU NF-e via SOAP — pendente de implementação sem pynfe."""
        raise NotImplementedError(
            'NF-e SOAP não implementado. pynfe foi removido. '
            'Implemente via requests+zeep ou biblioteca SOAP pura.'
        )

    # ── CT-e ────────────────────────────────────────────────────────────────

    def consulta_ctes_cnpj(self, cnpj: str, nsu: int) -> _RespostaAdapter:
        """distNSU CT-e via SOAP — pendente de implementação sem pynfe."""
        raise NotImplementedError(
            'CT-e SOAP não implementado. pynfe foi removido. '
            'Implemente via requests+zeep ou biblioteca SOAP pura.'
        )

    # ── NFS-e REST ADN ───────────────────────────────────────────────────────

    def enviar_requisicao_rest_mtls(self, url: str, metodo: str = 'GET') -> object:
        """
        Requisição REST com mTLS usando PFX em memória.
        PEM extraído on-the-fly via cryptography, dois temp files deletados no finally.
        """
        import requests
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat,
        )
        from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

        senha_bytes = self._senha.encode('utf-8') if isinstance(self._senha, str) else self._senha
        private_key, certificate, _ = load_key_and_certificates(self._pfx_bytes, senha_bytes)

        if not private_key or not certificate:
            raise ValueError('PFX não contém chave privada ou certificado válido.')

        cert_pem = certificate.public_bytes(Encoding.PEM)
        key_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

        fd_cert, cert_path = tempfile.mkstemp(suffix='.pem')
        fd_key, key_path = tempfile.mkstemp(suffix='.pem')
        try:
            os.write(fd_cert, cert_pem)
            os.close(fd_cert)
            os.write(fd_key, key_pem)
            os.close(fd_key)
            return requests.request(metodo, url, cert=(cert_path, key_path), timeout=30)
        finally:
            for path in (cert_path, key_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    # ── Manifestação ────────────────────────────────────────────────────────

    def enviar_manifestacao(self, cnpj: str, chave_nfe: str, tipo_evento: str = '210210') -> _RespostaAdapter:
        """Manifestação do Destinatário via SOAP — pendente de implementação sem pynfe."""
        raise NotImplementedError(
            'Manifestação SOAP não implementada. pynfe foi removido.'
        )


def inicializar_cliente_sefaz(cliente_obj, senha_certificado: str, homologacao: bool = True) -> ConectorSefaz:
    """
    Ponto de entrada da fábrica. Retorna ConectorSefaz pronto para NFS-e.
    NF-e e CT-e pendentes de implementação SOAP sem pynfe.
    """
    cert_db = CertificadoModel.objects.filter(cliente=cliente_obj, ativo=True).first()
    if not cert_db or not cert_db.conteudo_criptografado:
        raise ValueError(f'Nenhum certificado ativo encontrado para {cliente_obj.razao_social}')

    pfx_bytes = decrypt_a1(bytes(cert_db.conteudo_criptografado))

    uf = cliente_obj.uf.lower()
    codigo_uf = _UF_CODIGO.get(uf)
    if not codigo_uf:
        raise ValueError(f"UF inválida ou não suportada: '{cliente_obj.uf}'")

    return ConectorSefaz(
        pfx_bytes=pfx_bytes,
        senha=senha_certificado,
        uf=uf,
        codigo_uf=codigo_uf,
        homologacao=homologacao,
    )
