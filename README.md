# Control Financiero — Gastos y Pagos

Aplicación Django para registrar gastos y pagos de una empresa, con flujos de aprobación/cancelación,
pagos parciales, control de saldos bancarios, tablero con gráficos y API REST de solo lectura.

## Ejecutar en local
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
DEMO_USER=demo DEMO_PASSWORD=<contraseña> python manage.py crear_usuario_demo
python manage.py seed_demo
python manage.py runserver
```

## Pruebas
```bash
python manage.py test finanzas
```

## Despliegue (Render)
1. Subir el repositorio a GitHub.
2. En Render: **New → Blueprint** y seleccionar el repo (usa `render.yaml`: web service + PostgreSQL).
3. Definir `DEMO_USER` y `DEMO_PASSWORD` cuando Render los solicite.

## Documentación
- `docs/documentacion.odt` / `.docx` — entregable editable (exportar a PDF desde LibreOffice).
- `docs/diagramas/*.mmd` — diagramas Mermaid editables (+ `.png`/`.svg`).
- API: `/api/docs/` (Swagger) y `/api/`.
