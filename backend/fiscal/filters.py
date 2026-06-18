import django_filters
from .models import Documento


class DocumentoFilter(django_filters.FilterSet):
    # Filtro por período de emissão: ?data_emissao_inicio=2024-01-01&data_emissao_fim=2024-03-31
    data_emissao_inicio = django_filters.DateFilter(field_name='data_emissao', lookup_expr='gte')
    data_emissao_fim    = django_filters.DateFilter(field_name='data_emissao', lookup_expr='lte')
    # Filtro por faixa de valor: ?valor_min=100&valor_max=5000
    valor_min = django_filters.NumberFilter(field_name='valor', lookup_expr='gte')
    valor_max = django_filters.NumberFilter(field_name='valor', lookup_expr='lte')

    class Meta:
        model = Documento
        fields = {
            'cliente':        ['exact'],
            'competencia':    ['exact'],
            'tipo_documento': ['exact'],
            'status':         ['exact'],
            'papel_nfse':     ['exact'],
        }
