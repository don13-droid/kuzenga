# Kuzenga backend foundation reference

> **Status:** `kuzenga/` is now the authoritative Django project for Phase 1 consolidation. This directory is retained temporarily as an infrastructure reference. Do not add product applications or deploy it as a competing backend. The project owner has not approved its deletion or archival.

Useful patterns from this project (DRF defaults, environment-based settings, PostgreSQL, DB health behavior, and Docker/Gunicorn) have been integrated selectively into `../kuzenga/`.

The historical details below describe the standalone foundation as originally created; follow [`../kuzenga/README.md`](../kuzenga/README.md) for current development and runtime instructions.

This directory is a standalone Django REST Framework backend. It currently contains infrastructure and a database-aware health endpoint only.

## Local setup with Docker Compose

1. Copy `.env.example` to `.env` and replace the development secret and PostgreSQL password.
2. Run `docker compose up --build` from this directory. Compose applies database migrations before starting Gunicorn.
3. Check `http://localhost:8000/api/health/`.

For local Python work, install `requirements/development.txt` and run `python manage.py migrate` then `python manage.py runserver`. Set `DATABASE_URL` to a PostgreSQL instance reachable from the host (typically `localhost`, rather than Compose's `db` hostname).

Select settings with `DJANGO_SETTINGS_MODULE=config.settings.development`, `config.settings.testing`, or `config.settings.production`. Production requires `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, and PostgreSQL configuration.

Run `python -m pytest` and `python -m ruff check .` from this directory.
