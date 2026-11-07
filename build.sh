#!/usr/bin/env bash
# Script de build para Render
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py crear_usuario_demo
python manage.py seed_demo
