"""
Corrige o campo papel_nfse de documentos NFS-e capturados antes da
determinação automática de EMITENTE/TOMADOR via XML.

Execução: python manage.py backfill_papel
"""
import xml.etree.ElementTree as ET

from django.core.management.base import BaseCommand

from fiscal.conectores.nfse import _determinar_papel_nfse
from fiscal.models import Documento, Xml


class Command(BaseCommand):
    help = 'Corrige papel_nfse de documentos NFS-e com valor incorreto (ex: "NFSE").'

    def handle(self, *args, **options):
        qs = (
            Documento.objects
            .filter(tipo_documento='NFSE')
            .exclude(papel_nfse__in=('EMITENTE', 'TOMADOR'))
            .select_related('cliente')
        )
        total = qs.count()
        self.stdout.write(f'Documentos a corrigir: {total}')

        corrigidos = erros = sem_xml = 0

        for doc in qs.iterator(chunk_size=200):
            try:
                xml_obj = Xml.objects.get(documento=doc)
            except Xml.DoesNotExist:
                sem_xml += 1
                continue

            try:
                conteudo = xml_obj.conteudo
                raw = conteudo.encode('utf-8') if isinstance(conteudo, str) else conteudo
                root = ET.fromstring(raw)
            except ET.ParseError:
                erros += 1
                continue

            papel = _determinar_papel_nfse(root, doc.cliente.cnpj)
            if not papel:
                erros += 1
                continue

            doc.papel_nfse = papel
            meta = dict(doc.metadados or {})
            meta['papel_nfse'] = papel
            doc.metadados = meta
            doc.save(update_fields=['papel_nfse', 'metadados'])
            corrigidos += 1

        self.stdout.write(self.style.SUCCESS(
            f'Concluído — corrigidos: {corrigidos}, sem XML: {sem_xml}, erros: {erros}.'
        ))
