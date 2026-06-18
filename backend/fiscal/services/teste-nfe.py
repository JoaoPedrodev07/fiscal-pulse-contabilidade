import os
import sys
from dotenv import load_dotenv
from pynfe.processamento.comunicacao import ComunicacaoSefaz

load_dotenv()

def executar_hello_world():
    print("=== Iniciando Conexão Fiscal via PyNFe (Ambiente Windows) ===")
    
    # Coleta as variáveis do seu arquivo .env
    uf = os.getenv("SEFAZ_UF", "rs").lower()
    certificado_path = os.getenv("SEFAZ_CERT_PATH")
    senha = os.getenv("SEFAZ_CERT_SENHA")
    
    if not certificado_path or not senha:
        print("🚨 ERRO: Configure SEFAZ_CERT_PATH e SEFAZ_CERT_SENHA no seu arquivo .env")
        sys.exit(1)
        
    print(f"Alvo: Ambiente de HOMOLOGAÇÃO da SEFAZ [{uf.upper()}]")
    print(f"Certificado carregado de: {certificado_path}")
    
    try:
        # Inicializa o conector mTLS e SOAP encapsulado pela biblioteca
        con = ComunicacaoSefaz(uf, certificado_path, senha, homologacao=True)
        
        print("Enviando requisição de Status do Serviço...")
        xml_resposta = con.status_servico('nfe')
        
        print("\n🟢 RETORNO DO SERVIDOR DO GOVERNO:")
        print(f"HTTP Status: {xml_resposta.status_code}")
        print("-" * 50)
        print(xml_resposta.text)
        print("-" * 50)
        
    except Exception as e:
        print(f"\n🔴 FALHA NA CONEXÃO: {str(e)}")
        print("Verifique os caminhos no arquivo .env ou a validade do certificado.")

if __name__ == "__main__":
    executar_hello_world()