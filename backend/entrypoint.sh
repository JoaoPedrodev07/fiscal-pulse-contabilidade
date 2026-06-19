#!/usr/bin/env bash
set -e

echo "==> Rodando migrations..."
python manage.py migrate --noinput

echo "==> Criando superusuário (se não existir)..."
python manage.py ensure_superuser

echo "==> Iniciando gunicorn..."
exec gunicorn Projeto_Notas_Fiscas.wsgi:application
