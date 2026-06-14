"""
WSGI config for Projeto_Notas_Fiscas.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Projeto_Notas_Fiscas.settings')

application = get_wsgi_application()
