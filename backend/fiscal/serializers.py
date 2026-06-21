import datetime
import re

from rest_framework import serializers
from .models import Cliente, Certificado, ControleNSU, Documento, Escritorio, Xml, LogCaptura, LogAuditoriaNSU, Manifestacao


class EscritorioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Escritorio
        fields = ['id', 'razao_social', 'cnpj', 'ativo', 'criado_em']
        read_only_fields = ['id', 'criado_em']

    def validate_cnpj(self, value):
        if not re.fullmatch(r'\d{14}', value):
            raise serializers.ValidationError(
                'CNPJ deve conter exatamente 14 dígitos numéricos, sem pontuação.'
            )
        return value


class ClienteSerializer(serializers.ModelSerializer):
    escritorio_nome = serializers.CharField(source='escritorio.razao_social', read_only=True)

    class Meta:
        model = Cliente
        fields = ['id', 'escritorio', 'escritorio_nome', 'cnpj', 'razao_social', 'telefone', 'uf', 'ativo', 'criado_em']
        read_only_fields = ['id', 'criado_em', 'escritorio', 'escritorio_nome']

    def validate_cnpj(self, value):
        if not re.fullmatch(r'\d{14}', value):
            raise serializers.ValidationError(
                "CNPJ deve conter exatamente 14 dígitos numéricos, sem pontuação."
            )
        return value


class CertificadoSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.razao_social', read_only=True)
    cliente = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.all())

    class Meta:
        model = Certificado
        fields = ['id', 'cliente', 'cliente_nome', 'nome_arquivo', 'validade', 'ativo', 'criado_em']
        read_only_fields = ['id', 'criado_em']


class ControleNSUSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.razao_social', read_only=True)

    class Meta:
        model = ControleNSU
        fields = ['id', 'cliente', 'cliente_nome', 'tipo_documento', 'ultimo_nsu', 'max_nsu', 'atualizado_em']
        read_only_fields = ['id', 'atualizado_em']



from cryptography.hazmat.primitives.serialization import pkcs12
from fiscal.services.cofre import encrypt_a1

class CertificadoCreateSerializer(serializers.Serializer):
    """Cria e encripta o certificado em uma única chamada multipart/form-data."""
    cliente = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.all())
    arquivo = serializers.FileField()
    senha   = serializers.CharField(write_only=True)

    def validate(self, data):
        senha = data['senha'].encode()
        try:
            pfx_bytes = data['arquivo'].read()
            _, certificate, _ = pkcs12.load_key_and_certificates(pfx_bytes, senha)
            if not certificate:
                raise serializers.ValidationError("Certificado não encontrado no arquivo PFX.")
            data_validade = certificate.not_valid_after_utc.date()
            if data_validade < datetime.date.today():
                raise serializers.ValidationError("Este certificado digital já está expirado.")
            data['pfx_bytes'] = pfx_bytes
            data['data_validade'] = data_validade
        except ValueError:
            raise serializers.ValidationError("Senha incorreta ou arquivo de certificado inválido.")
        except serializers.ValidationError:
            raise
        except Exception as e:
            raise serializers.ValidationError(f"Erro no processamento: {str(e)}")
        return data

    def create(self, validated_data):
        return Certificado.objects.create(
            cliente=validated_data['cliente'],
            nome_arquivo=validated_data['arquivo'].name,
            validade=validated_data['data_validade'],
            conteudo_criptografado=encrypt_a1(validated_data['pfx_bytes']),
            senha_criptografada=encrypt_a1(validated_data['senha'].encode('utf-8')),
            ativo=True,
        )


class CertificadoUploadSerializer(serializers.ModelSerializer):
    # Campos que recebem o payload multipart/form-data
    arquivo = serializers.FileField(write_only=True)
    senha = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta:
        model = Certificado
        fields = ['arquivo', 'senha']

    def validate(self, data):
        arquivo = data['arquivo']
        senha = data['senha'].encode()  # O cryptography exige bytes para decodificar
        
        try:
            pfx_bytes = arquivo.read()
            # 1. Valida o certificado direto na RAM (Não salva a senha aberta em lugar nenhum)
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                pfx_bytes, 
                senha
            )
            
            if certificate:
                # 2. Extrai a validade real gravada dentro das propriedades do PFX
                data_validade = certificate.not_valid_after_utc.date()
                if data_validade < datetime.date.today():
                    raise serializers.ValidationError("Este certificado digital já está expirado.")
                
                # Guarda os dados processados para o método update
                data['pfx_bytes'] = pfx_bytes
                data['data_validade'] = data_validade
            else:
                raise serializers.ValidationError("Não foi possível localizar um certificado válido dentro deste arquivo PFX.")
                
        except ValueError:
            # O pkcs12 dispara ValueError se o arquivo estiver corrompido ou se a senha estiver errada
            raise serializers.ValidationError("Senha incorreta ou arquivo de certificado inválido.")
        except Exception as e:
            raise serializers.ValidationError(f"Erro no processamento do arquivo: {str(e)}")

        return data

    def update(self, instance, validated_data):
        pfx_bytes = validated_data['pfx_bytes']
        senha_pura = validated_data['senha'] # Pega a string que veio do input

        # 🚀 Criptografa ambos usando seu cofre stateless
        instance.conteudo_criptografado = encrypt_a1(pfx_bytes)
        instance.senha_criptografada = encrypt_a1(senha_pura.encode('utf-8'))
        
        instance.validade = validated_data['data_validade']
        instance.nome_arquivo = validated_data['arquivo'].name
        instance.ativo = True
        instance.save()
        
        return instance
class XmlSerializer(serializers.ModelSerializer):
    class Meta:
        model = Xml
        fields = ['conteudo', 'criado_em']
        read_only_fields = ['criado_em']


class DocumentoSerializer(serializers.ModelSerializer):
    cliente_nome            = serializers.CharField(source='cliente.razao_social', read_only=True)
    divergencia_competencia = serializers.SerializerMethodField()

    def get_divergencia_competencia(self, obj) -> bool:
        """True quando mês/ano da emissão difere da competência declarada."""
        return obj.data_emissao.strftime('%Y-%m') != obj.competencia

    class Meta:
        model = Documento
        fields = [
            'id', 'cliente', 'cliente_nome',
            'chave', 'tipo_documento', 'emitente',
            'valor', 'data_emissao', 'competencia',
            'divergencia_competencia',
            'status', 'papel_nfse', 'metadados', 'criado_em',
        ]
        read_only_fields = ['id', 'criado_em']

    def validate_competencia(self, value):
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', value):
            raise serializers.ValidationError(
                "Competencia deve estar no formato AAAA-MM (ex: 2024-01)."
            )
        return value


class DocumentoDetalheSerializer(DocumentoSerializer):
    xml = XmlSerializer(read_only=True)

    class Meta(DocumentoSerializer.Meta):
        fields = DocumentoSerializer.Meta.fields + ['xml']


class LogCapturaSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.razao_social', read_only=True)

    class Meta:
        model = LogCaptura
        fields = ['id', 'cliente', 'cliente_nome', 'tipo_documento', 'sucesso', 'mensagem', 'executado_em']
        read_only_fields = ['id', 'executado_em']


class LogAuditoriaNSUSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.razao_social', read_only=True)

    class Meta:
        model = LogAuditoriaNSU
        fields = ['id', 'cliente', 'cliente_nome', 'tipo_documento', 'nsu', 'resultado', 'chave', 'executado_em']
        read_only_fields = ['id', 'executado_em']


class ManifestacaoSerializer(serializers.ModelSerializer):
    documento_chave = serializers.CharField(source='documento.chave', read_only=True)
    cliente_nome = serializers.CharField(source='documento.cliente.razao_social', read_only=True)

    class Meta:
        model = Manifestacao
        fields = [
            'id', 'documento', 'documento_chave', 'cliente_nome',
            'tipo_evento', 'protocolo', 'sucesso', 'mensagem', 'enviado_em',
        ]
        read_only_fields = ['id', 'enviado_em']
