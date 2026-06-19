import logging
import sys
import threading
import time

from django.apps import AppConfig

logger = logging.getLogger(__name__)

_INTERVALO_SEGUNDOS = 4 * 3600  # 4 horas
_WARMUP_SEGUNDOS    = 90        # aguarda gunicorn estabilizar antes da primeira captura


def _loop_captura():
    time.sleep(_WARMUP_SEGUNDOS)
    while True:
        try:
            from fiscal.tasks import executar_recolhimento_lote_nsu
            logger.info('==> [scheduler] Iniciando ciclo automatico de captura.')
            executar_recolhimento_lote_nsu()
            logger.info('==> [scheduler] Ciclo concluido.')
        except Exception as exc:
            logger.error('==> [scheduler] Falha no ciclo de captura: %s', exc)
        time.sleep(_INTERVALO_SEGUNDOS)


class FiscalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fiscal'
    verbose_name = 'Fiscal'

    def ready(self):
        # Inicia o agendador apenas quando rodando como servidor web (gunicorn).
        # manage.py sempre tem 'manage.py' em sys.argv[0]; gunicorn nao tem.
        if 'manage.py' in sys.argv[0]:
            return

        t = threading.Thread(target=_loop_captura, name='captura-scheduler', daemon=True)
        t.start()
        logger.info('==> [scheduler] Thread de captura automatica iniciada (intervalo=%dh).', _INTERVALO_SEGUNDOS // 3600)
