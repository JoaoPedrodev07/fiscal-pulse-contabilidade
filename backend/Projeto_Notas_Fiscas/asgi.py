"""
ASGI config for Projeto_Notas_Fiscas.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Projeto_Notas_Fiscas.settings')

application = get_asgi_application()
