"""
Corrige papel_nfse de documentos NFS-e capturados com TipoDocumento='NFSE'.
O ADN de produção retorna TipoDocumento='NFSE' (tipo do doc, não o papel).
Esta migration relê o XML armazenado e determina EMITENTE/TOMADOR comparando
o CNPJ do prestador (<emit>/<prest>) com o CNPJ do cliente.
"""
import xml.etree.ElementTree as ET

from django.db import migrations


def _cnpj_em_secao(root, *secoes):
    lower = {s.lower() for s in secoes}
    for el in root.iter():
        if el.tag.split('}')[-1].lower() in lower:
            for child in el.iter():
                if child.tag.split('}')[-1].lower() == 'cnpj' and child.text:
                    digits = ''.join(c for c in child.text if c.isdigit())
                    if len(digits) == 14:
                        return digits
    return ''


def backfill_papel(apps, schema_editor):
    Documento = apps.get_model('fiscal', 'Documento')
    Xml = apps.get_model('fiscal', 'Xml')

    docs = Documento.objects.filter(
        tipo_documento='NFSE',
    ).exclude(papel_nfse__in=('EMITENTE', 'TOMADOR')).select_related('cliente')

    for doc in docs.iterator(chunk_size=200):
        try:
            xml_obj = Xml.objects.get(documento=doc)
        except Xml.DoesNotExist:
            continue

        try:
            raw = xml_obj.conteudo
            if isinstance(raw, str):
                raw = raw.encode('utf-8')
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue

        prestador_cnpj = _cnpj_em_secao(
            root, 'emit', 'prest', 'emitente', 'prestador', 'dadosprestador', 'infprestador',
        )
        if not prestador_cnpj:
            continue

        papel = 'EMITENTE' if prestador_cnpj == doc.cliente.cnpj else 'TOMADOR'

        meta = dict(doc.metadados or {})
        meta['papel_nfse'] = papel
        doc.papel_nfse = papel
        doc.metadados = meta
        doc.save(update_fields=['papel_nfse', 'metadados'])


class Migration(migrations.Migration):

    dependencies = [
        ('fiscal', '0012_botoderma_is_staff'),
    ]

    operations = [
        migrations.RunPython(backfill_papel, migrations.RunPython.noop),
    ]
