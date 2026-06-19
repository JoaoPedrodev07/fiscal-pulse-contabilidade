#!/usr/bin/env bash
set -e

echo "==> Rodando migrations..."
python manage.py migrate --noinput

echo "==> Criando superusuário (se não existir)..."
python manage.py ensure_superuser

echo "==> Criando usuários de clientes..."
python manage.py ensure_client_users

echo "==> Corrigindo papel_nfse de documentos NFS-e..."
python manage.py backfill_papel

echo "==> Iniciando gunicorn..."
exec gunicorn Projeto_Notas_Fiscas.wsgi:application
