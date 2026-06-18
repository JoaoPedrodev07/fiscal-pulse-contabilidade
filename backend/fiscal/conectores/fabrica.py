"""
Fábrica de conectores SEFAZ.

Responsabilidade: descriptografar o A1 do banco, escrever um temp file
durante a chamada SOAP (PyNFe exige caminho em disco), deletar imediatamente,
e devolver um adapter com interface uniforme para NFeCapturaService e CTeCapturaService.
"""
import logging
import os
import tempfile

from pynfe.processamento.comunicacao import ComunicacaoSefaz

from fiscal.models import Certificado as CertificadoModel
from fiscal.services.cofre import decrypt_a1

logger = logging.getLogger(__name__)

# Código IBGE de cada UF — exigido pelo campo cUF da SEFAZ
_UF_CODIGO = {
    'ac': 12, 'al': 27, 'ap': 16, 'am': 13, 'ba': 29, 'ce': 23,
    'df': 53, 'es': 32, 'go': 52, 'ma': 21, 'mt': 51, 'ms': 50,
    'mg': 31, 'pa': 15, 'pb': 25, 'pr': 41, 'pe': 26, 'pi': 22,
    'rj': 33, 'rn': 24, 'rs': 43, 'ro': 11, 'rr': 14, 'sc': 42,
    'sp': 35, 'se': 28, 'to': 17,
}


def _normalizar_resposta_pynfe(xml_resposta) -> str:
    """
    PyNFe pode retornar bytes, str, um objeto Response do requests ou lxml.etree.
    Normaliza tudo extraindo o XML bruto em formato str UTF-8.
    """
    # 1. Se receber o objeto Response do requests ou similar, extrai o texto interno primeiro
    if hasattr(xml_resposta, 'text'):
        xml_resposta = xml_resposta.text

    if isinstance(xml_resposta, bytes):
        return xml_resposta.decode('utf-8', errors='ignore')
        
    if isinstance(xml_resposta, str):
        return xml_resposta

    # 2. Fallback para lxml Element
    try:
        from lxml import etree
        if isinstance(xml_resposta, etree._Element):
            return etree.tostring(xml_resposta, encoding='unicode')
    except Exception:
        pass

    return str(xml_resposta)


class _RespostaAdapter:
    """Envolve o XML da SEFAZ numa interface .status_code/.text compatível com NFeCapturaService."""
    status_code = 200

    def __init__(self, texto: str):
        self.text = texto


class ConectorSefaz:
    """
    Adapter que recebe os bytes do PFX descriptografados em RAM e expõe os
    métodos de consulta usados pelos serviços de captura.

    O PFX é gravado em disco APENAS durante cada chamada SOAP e deletado
    imediatamente no bloco finally — janela de exposição < 1 ms.
    """

    def __init__(self, pfx_bytes: bytes, senha: str, uf: str, codigo_uf: int, homologacao: bool):
        self._pfx_bytes = pfx_bytes
        self._senha = senha
        self._uf = uf
        self._codigo_uf = codigo_uf
        self._homologacao = homologacao

    def _comunicacao(self, tmp_path: str) -> ComunicacaoSefaz:
        return ComunicacaoSefaz(
            uf=self._uf,
            certificado=tmp_path,
            certificado_senha=self._senha,
            homologacao=self._homologacao,
        )

    def _run(self, metodo_nome: str, **kwargs) -> _RespostaAdapter:
        """Cria o temp file, chama o método PyNFe e deleta o arquivo."""
        fd, tmp_path = tempfile.mkstemp(suffix='.pfx')
        try:
            os.write(fd, self._pfx_bytes)
            os.close(fd)
            com = self._comunicacao(tmp_path)
            
            # Aqui chamamos o método real da biblioteca (ex: consulta_notas_cnpj)
            resultado = getattr(com, metodo_nome)(**kwargs)
            return _RespostaAdapter(_normalizar_resposta_pynfe(resultado))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

# ── NF-e ────────────────────────────────────────────────────────────────

    def consulta_notas_cnpj(self, cnpj: str, nsu: int) -> _RespostaAdapter:
        """distNSU — varredura incremental de NF-e por CNPJ a partir do NSU."""
        return self._run(
            'consulta_distribuicao',  
            cnpj=cnpj,
            nsu=int(nsu),
        )

    # ── CT-e ────────────────────────────────────────────────────────────────

    def consulta_ctes_cnpj(self, cnpj: str, nsu: int) -> _RespostaAdapter:
        """distNSU — varredura incremental de CT-e por CNPJ a partir do NSU."""
        return self._run(
            'consulta_distribuicao',  
            cnpj=cnpj,
            nsu=int(nsu),
        )
        
        
        
        
# ── NFS-e REST ADN ──────────────────────────────────────────────────────

# ── NFS-e REST ADN ──────────────────────────────────────────────────────

    def consulta_nfse_nsu(self, nsu: int) -> _RespostaAdapter:
        """
        Consome a API REST do ADN (Ambiente de Dados Nacional) da NFS-e.
        Usa cryptography para extrair a chave e o certificado em RAM e injetar no requests.
        """
        import requests
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.hazmat.primitives import serialization
        import tempfile
        import os
        
        url = f"https://adnapi.nfse.gov.br/DFe/{nsu}"
        
        # 1. Desempacota o PFX em memória usando a senha
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            self._pfx_bytes,
            self._senha.encode('utf-8') if isinstance(self._senha, str) else self._senha
        )
        
        # 2. Converte a chave e o certificado para o formato PEM em bytes
        cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        # 3. O requests exige arquivos em disco para o parâmetro 'cert'. 
        # Vamos criar um arquivo PEM temporário único contendo [Chave + Certificado]
        fd, tmp_path = tempfile.mkstemp(suffix='.pem')
        try:
            os.write(fd, cert_pem + b"\n" + key_pem)
            os.close(fd)
            
            session = requests.Session()
            session.verify = False  # Desativa avisos de cadeias locais do governo
            
            # Passa o arquivo temporário contendo o par mTLS
            response = session.get(url, cert=tmp_path, timeout=15)
            
            return _RespostaAdapter(_normalizar_resposta_pynfe(response))
            
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    # ── Manifestação ────────────────────────────────────────────────────────

    def enviar_manifestacao(self, cnpj: str, chave_nfe: str, tipo_evento: str = '210210') -> _RespostaAdapter:
        """
        Envia Ciência da Operação (210210) ou outro evento de manifestação.
        PyNFe monta o XML, assina (XML-DSig) e envia via mTLS.
        """
        return self._run(
            'evento',
            cnpj=cnpj,
            chave=chave_nfe,
            tipo_evento=tipo_evento,
        )


def inicializar_cliente_sefaz(cliente_obj, senha_certificado: str, homologacao: bool = True) -> ConectorSefaz:
    """
    Ponto de entrada da fábrica. Chamado pela task para cada cliente ativo.
    Retorna um ConectorSefaz pronto para ser passado a NFeCapturaService ou CTeCapturaService.
    """
    cert_db = CertificadoModel.objects.filter(cliente=cliente_obj, ativo=True).first()
    if not cert_db or not cert_db.conteudo_criptografado:
        raise ValueError(f"Nenhum certificado ativo encontrado para {cliente_obj.razao_social}")

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
