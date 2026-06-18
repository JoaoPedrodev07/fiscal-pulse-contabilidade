import os
from celery import Celery

# 1. Define o Django settings padrão para o Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Projeto_Notas_Fiscas.settings')

app = Celery('Projeto_Notas_Fiscas')

# 2. Lê as configurações do Celery direto do settings.py usando o prefixo CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# 3. Descobre automaticamente tarefas em arquivos tasks.py dentro de todos os apps instalados
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')