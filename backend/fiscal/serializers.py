import re

from rest_framework import serializers
from .models import Cliente, Certificado, ControleNSU, Documento, Xml, LogCaptura


class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = ['id', 'cnpj', 'razao_social', 'telefone', 'ativo', 'criado_em']
        read_only_fields = ['id', 'criado_em']

    def validate_cnpj(self, value):
        if not re.fullmatch(r'\d{14}', value):
            raise serializers.ValidationError(
                "CNPJ deve conter exatamente 14 dígitos numéricos, sem pontuação."
            )
        return value


class CertificadoSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.razao_social', read_only=True)
    cliente = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.all(), write_only=True)

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


class XmlSerializer(serializers.ModelSerializer):
    class Meta:
        model = Xml
        fields = ['conteudo', 'criado_em']
        read_only_fields = ['criado_em']


class DocumentoSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.razao_social', read_only=True)

    class Meta:
        model = Documento
        fields = [
            'id', 'cliente', 'cliente_nome',
            'chave', 'tipo_documento', 'emitente',
            'valor', 'data_emissao', 'competencia',
            'status', 'metadados', 'criado_em',
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
