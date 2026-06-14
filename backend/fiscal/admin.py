from django.contrib import admin
from .models import Cliente, Certificado, ControleNSU, Documento, Xml, LogCaptura


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('razao_social', 'cnpj', 'telefone', 'ativo', 'criado_em')
    list_filter = ('ativo',)
    search_fields = ('razao_social', 'cnpj')
    ordering = ['razao_social']


@admin.register(Certificado)
class CertificadoAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'nome_arquivo', 'validade', 'ativo')
    list_filter = ('ativo',)
    search_fields = ('cliente__razao_social', 'cliente__cnpj', 'nome_arquivo')
    autocomplete_fields = ['cliente']


@admin.register(ControleNSU)
class ControleNSUAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'tipo_documento', 'ultimo_nsu', 'max_nsu', 'atualizado_em')
    list_filter = ('tipo_documento',)
    search_fields = ('cliente__razao_social', 'cliente__cnpj')


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ('chave', 'tipo_documento', 'cliente', 'emitente', 'valor', 'data_emissao', 'competencia', 'status')
    list_filter = ('tipo_documento', 'status')
    search_fields = ('chave', 'emitente', 'cliente__razao_social', 'cliente__cnpj')
    date_hierarchy = 'data_emissao'
    autocomplete_fields = ['cliente']


@admin.register(Xml)
class XmlAdmin(admin.ModelAdmin):
    list_display = ('documento', 'criado_em')
    search_fields = ('documento__chave',)


@admin.register(LogCaptura)
class LogCapturaAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'tipo_documento', 'sucesso', 'executado_em')
    list_filter = ('sucesso', 'tipo_documento')
    search_fields = ('cliente__razao_social', 'cliente__cnpj')
