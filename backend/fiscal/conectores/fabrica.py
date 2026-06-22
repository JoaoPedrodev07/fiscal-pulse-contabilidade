"""
Fábrica de conectores SEFAZ.

Comunicação fiscal usa apenas requests + cryptography:
- NFS-e: REST mTLS via ADN (requests)
- NF-e / CT-e: SOAP distNSU via SOAP 1.2 + mTLS (requests)
"""
import contextlib
import logging
import os
import tempfile
import xml.etree.ElementTree as ET

import requests

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

_URL_NFE = {
    True:  'https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
    False: 'https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
}
_URL_CTE = {
    True:  'https://homologacao.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx',
    False: 'https://www.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx',
}

_SOAP_ACTION_NFE = 'http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse'
_SOAP_ACTION_CTE = 'http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe/cteDistDFeInteresse'

_TP_AMB = {True: '2', False: '1'}  # 2=homologação, 1=produção


def _extrair_conteudo_soap(texto_soap: str) -> str:
    """
    Extrai o retDistDFeInt da resposta SOAP da SEFAZ como string XML.
    Retorna o texto original como fallback se não encontrar ou se não for XML.
    """
    try:
        root = ET.fromstring(texto_soap.encode('utf-8'))
        for el in root.iter():
            local = el.tag.split('}')[-1] if '}' in el.tag else el.tag
            if local == 'retDistDFeInt':
                return ET.tostring(el, encoding='unicode')
        return texto_soap
    except ET.ParseError:
        return texto_soap


class _RespostaAdapter:
    """Interface .status_code/.text compatível com NFeCapturaService e CTeCapturaService."""
    status_code = 200

    def __init__(self, texto: str):
        self.text = texto


class ConectorSefaz:
    """
    Adapter que mantém o PFX descriptografado em RAM e expõe os métodos
    de consulta usados pelos serviços de captura.

    O PFX é gravado em disco APENAS durante chamadas (PEM temporário)
    e deletado imediatamente no bloco finally.
    """

    def __init__(self, pfx_bytes: bytes, senha: str, uf: str, codigo_uf: int, homologacao: bool):
        self._pfx_bytes = pfx_bytes
        self._senha = senha
        self._uf = uf
        self._codigo_uf = codigo_uf
        self._homologacao = homologacao

    # ── Utilitários de certificado ───────────────────────────────────────────

    @contextlib.contextmanager
    def _extrair_pem_temp(self):
        """
        Context manager: extrai cert+chave PEM do PKCS12 para arquivos temporários.
        Garante deleção mesmo em exceção. Yields (cert_path, key_path).
        """
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
            yield cert_path, key_path
        finally:
            for path in (cert_path, key_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _soap_mtls(self, url: str, envelope: str, soap_action: str) -> '_RespostaAdapter':
        """
        Envia envelope SOAP via POST mTLS.
        Propaga requests.exceptions.* sem silenciar — quem chama decide o tratamento.
        """
        headers = {
            'Content-Type': 'application/soap+xml; charset=utf-8',
            'SOAPAction': soap_action,
        }
        with self._extrair_pem_temp() as (cert_path, key_path):
            resp = requests.post(
                url,
                data=envelope.encode('utf-8'),
                headers=headers,
                cert=(cert_path, key_path),
                timeout=30,
            )

        conteudo = _extrair_conteudo_soap(resp.text)
        adapter = _RespostaAdapter(conteudo)
        adapter.status_code = resp.status_code
        return adapter

    # ── NF-e ────────────────────────────────────────────────────────────────

    def consulta_notas_cnpj(self, cnpj: str, nsu: int) -> '_RespostaAdapter':
        """distNSU NF-e via SOAP 1.2 + mTLS."""
        nsu_fmt = f'{nsu:015d}'
        tp_amb = _TP_AMB[self._homologacao]
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
            '<soap12:Body>'
            '<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">'
            f'<distDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">'
            f'<tpAmb>{tp_amb}</tpAmb>'
            f'<cUFAutor>{self._codigo_uf}</cUFAutor>'
            f'<CNPJ>{cnpj}</CNPJ>'
            '<distNSU>'
            f'<ultNSU>{nsu_fmt}</ultNSU>'
            '</distNSU>'
            '</distDFeInt>'
            '</nfeDadosMsg>'
            '</soap12:Body>'
            '</soap12:Envelope>'
        )
        logger.info(
            '[NFE-SOAP] distNSU cnpj=%.8s... nsu=%s env=%s',
            cnpj, nsu_fmt, 'hom' if self._homologacao else 'prod',
        )
        return self._soap_mtls(_URL_NFE[self._homologacao], envelope, _SOAP_ACTION_NFE)

    # ── CT-e ────────────────────────────────────────────────────────────────

    def consulta_ctes_cnpj(self, cnpj: str, nsu: int) -> '_RespostaAdapter':
        """distNSU CT-e via SOAP 1.2 + mTLS."""
        nsu_fmt = f'{nsu:015d}'
        tp_amb = _TP_AMB[self._homologacao]
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
            '<soap12:Body>'
            '<cteDadosMsg xmlns="http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe">'
            f'<distDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/cte">'
            f'<tpAmb>{tp_amb}</tpAmb>'
            f'<cUFAutor>{self._codigo_uf}</cUFAutor>'
            f'<CNPJ>{cnpj}</CNPJ>'
            '<distNSU>'
            f'<ultNSU>{nsu_fmt}</ultNSU>'
            '</distNSU>'
            '</distDFeInt>'
            '</cteDadosMsg>'
            '</soap12:Body>'
            '</soap12:Envelope>'
        )
        logger.info(
            '[CTE-SOAP] distNSU cnpj=%.8s... nsu=%s env=%s',
            cnpj, nsu_fmt, 'hom' if self._homologacao else 'prod',
        )
        return self._soap_mtls(_URL_CTE[self._homologacao], envelope, _SOAP_ACTION_CTE)

    # ── NFS-e REST ADN ───────────────────────────────────────────────────────

    def enviar_requisicao_rest_mtls(self, url: str, metodo: str = 'GET') -> object:
        """Requisição REST com mTLS usando PFX em memória."""
        with self._extrair_pem_temp() as (cert_path, key_path):
            return requests.request(metodo, url, cert=(cert_path, key_path), timeout=30)

    # ── Manifestação ────────────────────────────────────────────────────────

    def enviar_manifestacao(self, cnpj: str, chave_nfe: str, tipo_evento: str = '210210') -> '_RespostaAdapter':
        """Manifestação do Destinatário via SOAP — pendente de implementação."""
        raise NotImplementedError('Manifestação SOAP não implementada.')


def inicializar_cliente_sefaz(cliente_obj, senha_certificado: str, homologacao: bool = True) -> ConectorSefaz:
    """
    Ponto de entrada da fábrica. Retorna ConectorSefaz pronto para NFS-e, NF-e e CT-e.
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
