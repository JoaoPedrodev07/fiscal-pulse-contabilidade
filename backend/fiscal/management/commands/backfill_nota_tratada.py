"""
Popula NotaTratada para todos os documentos NFS-e que já têm XML salvo
mas ainda não têm registro tratado (capturados antes da integração).

Execução:
    python manage.py backfill_nota_tratada
    python manage.py backfill_nota_tratada --cliente 42   # só um cliente
    python manage.py backfill_nota_tratada --force        # reprocessa mesmo os que já têm registro
"""
from django.core.management.base import BaseCommand

from fiscal.conectores.nfse import _salvar_nota_tratada
from fiscal.models import Documento, NotaTratada, Xml


class Command(BaseCommand):
    help = 'Preenche NotaTratada para documentos NFS-e com XML já salvo.'

    def add_arguments(self, parser):
        parser.add_argument('--cliente', type=int, help='Processar apenas este cliente_id')
        parser.add_argument('--force', action='store_true',
                            help='Reprocessa mesmo documentos que já têm NotaTratada')

    def handle(self, *args, **options):
        qs = (
            Documento.objects
            .filter(tipo_documento='NFSE')
            .select_related('cliente')
            .prefetch_related('xml')
        )
        if options['cliente']:
            qs = qs.filter(cliente_id=options['cliente'])
        if not options['force']:
            ids_com_nota = NotaTratada.objects.values_list('documento_id', flat=True)
            qs = qs.exclude(id__in=ids_com_nota)

        total = qs.count()
        self.stdout.write(f'Documentos a processar: {total}')

        ok = sem_xml = erros = 0

        for doc in qs.iterator(chunk_size=200):
            try:
                xml_obj = doc.xml
            except Documento.xml.RelatedObjectDoesNotExist:
                sem_xml += 1
                continue

            try:
                _salvar_nota_tratada(doc, xml_obj.conteudo, doc.status, doc.papel_nfse)
                ok += 1
            except Exception as exc:
                erros += 1
                self.stderr.write(f'  Erro doc {doc.id}: {exc}')

        self.stdout.write(self.style.SUCCESS(
            f'Concluído — processados: {ok}, sem XML: {sem_xml}, erros: {erros}.'
        ))
