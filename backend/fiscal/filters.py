import django_filters
from django.db.models import F, Func, CharField, Value, Q
from .models import Documento


class _ToChar(Func):
    """TO_CHAR do PostgreSQL — converte data para 'YYYY-MM' comparavel com o campo competencia."""
    function = 'TO_CHAR'
    output_field = CharField()


class DocumentoFilter(django_filters.FilterSet):
    data_emissao_inicio    = django_filters.DateFilter(field_name='data_emissao', lookup_expr='gte')
    data_emissao_fim       = django_filters.DateFilter(field_name='data_emissao', lookup_expr='lte')
    valor_min              = django_filters.NumberFilter(field_name='valor', lookup_expr='gte')
    valor_max              = django_filters.NumberFilter(field_name='valor', lookup_expr='lte')
    competencia_divergente = django_filters.BooleanFilter(method='filter_competencia_divergente')

    class Meta:
        model = Documento
        fields = {
            'cliente':        ['exact'],
            'competencia':    ['exact'],
            'tipo_documento': ['exact'],
            'status':         ['exact'],
            'papel_nfse':     ['exact'],
        }

    def filter_competencia_divergente(self, queryset, name, value):
        """
        true  → notas onde YYYY-MM(data_emissao) != competencia  (divergentes)
        false → notas onde YYYY-MM(data_emissao) == competencia  (consistentes)
        """
        if value is None:
            return queryset
        qs = queryset.annotate(
            _emissao_ym=_ToChar(F('data_emissao'), Value('YYYY-MM'))
        )
        return qs.filter(~Q(_emissao_ym=F('competencia'))) if value else qs.filter(_emissao_ym=F('competencia'))
