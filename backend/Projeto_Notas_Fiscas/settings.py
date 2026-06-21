"""
Django settings for Projeto_Notas_Fiscas.
"""
import os
import urllib.parse
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env', override=True)
except ImportError:
    pass

DEBUG = os.environ.get('DEBUG', 'True') in ('True', 'true', '1')

_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if DEBUG:
        _secret = 'dev-only-insecure-key-nao-usar-em-producao'
    else:
        raise RuntimeError(
            "A variável de ambiente SECRET_KEY é obrigatória em produção."
        )
SECRET_KEY = _secret


def _split_env_list(name: str) -> list[str]:
    raw = os.environ.get(name, '')
    return [item.strip() for item in raw.split(',') if item.strip()]


ALLOWED_HOSTS = _split_env_list('ALLOWED_HOSTS')
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1']

INSTALLED_APPS = [
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'django_filters',
    'users.apps.UsersConfig',
    'fiscal.apps.FiscalConfig',
    'django_celery_beat',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOWED_ORIGINS = _split_env_list('CORS_ALLOWED_ORIGINS')
if DEBUG and not CORS_ALLOWED_ORIGINS:
    CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = 'Projeto_Notas_Fiscas.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'Projeto_Notas_Fiscas.wsgi.application'

# ── Banco de dados ──────────────────────────────────────────────────────────────

def _clean_db_url(url: str) -> str:
    """Remove sslmode da query string — OPTIONS['sslmode'] é o caminho correto."""
    parsed = urllib.parse.urlparse(url)
    qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items() if k != 'sslmode'}
    return parsed._replace(query=urllib.parse.urlencode(qs)).geturl()

_raw_db_url = os.environ.get('DATABASE_URL', '')

if _raw_db_url:
    # DATABASE_URL definida: sempre usa PostgreSQL (dev local ou produção)
    DATABASES = {
        'default': dj_database_url.parse(
            _clean_db_url(_raw_db_url),
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
    if DATABASES['default'].get('ENGINE') == 'django.db.backends.postgresql':
        DATABASES['default'].setdefault('OPTIONS', {})
        DATABASES['default']['OPTIONS']['sslmode'] = 'require'
else:
    # Sem DATABASE_URL: SQLite apenas para desenvolvimento sem banco configurado
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ── Segurança ───────────────────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ── Internacionalização ─────────────────────────────────────────────────────────

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# ── Static / Media ──────────────────────────────────────────────────────────────

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')


def _s3_custom_domain(bucket_name: str, region_name: str) -> str:
    if region_name == 'us-east-1':
        return f'{bucket_name}.s3.amazonaws.com'
    return f'{bucket_name}.s3.{region_name}.amazonaws.com'


USE_S3 = bool(os.environ.get('AWS_STORAGE_BUCKET_NAME'))

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

if USE_S3:
    if 'storages' not in INSTALLED_APPS:
        INSTALLED_APPS.append('storages')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_QUERYSTRING_AUTH = False
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_S3_CUSTOM_DOMAIN = os.environ.get(
        'AWS_S3_CUSTOM_DOMAIN',
        _s3_custom_domain(AWS_STORAGE_BUCKET_NAME, AWS_S3_REGION_NAME),
    )
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
    STORAGES['default'] = {
        'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
        'OPTIONS': {'location': 'media'},
    }
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ── DRF ────────────────────────────────────────────────────────────────────────

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'users.User'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'EXCEPTION_HANDLER': 'users.views.exception_handler_pt',
}

# ── Celery ──────────────────────────────────────────────────────────────────────

CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_TIMEZONE = 'America/Sao_Paulo'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutos — limite rígido por tarefa

if DEBUG:
    # Local sem Redis: executa as tasks de forma síncrona na mesma thread
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

CELERY_BEAT_SCHEDULE = {
    'captura-automatica-nfe-cte-carteira': {
        'task': 'fiscal.tasks.executar_recolhimento_lote_nsu',
        'schedule': 14400.0,  # 4 horas
        'options': {'expires': 3600},
    },
}
