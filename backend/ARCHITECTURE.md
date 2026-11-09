# Backend foundation decisions (reference project)

> **Status:** The canonical application is now `../kuzenga/`. This file records the original standalone foundation decisions for reference; it is not the active project configuration or an approved deployment architecture.

- `backend/` is an isolated Django project. Existing frontend and legacy project files at the repository root remain untouched.
- Settings are split into shared, development, testing, and production modules. Runtime configuration is read from environment variables with `django-environ`.
- PostgreSQL is the required runtime database. SQLite is not configured as a silent fallback; Compose provides PostgreSQL for local runs.
- DRF is installed and configured for JSON APIs. The initial health endpoint is public and checks database connectivity.
- `USE_TZ` is enabled and UTC is the default timezone; deployments may set `TIME_ZONE` explicitly.
- Static and uploaded media have separate collection/storage roots. Production media serving should be delegated to object storage or a web server as deployment evolves.
- Production requires a real secret and allowed hosts, and enables HTTPS redirects, secure cookies, HSTS, and common browser security headers.
- Business domains, authentication customization, and multi-tenancy are intentionally outside this infrastructure foundation.
- Dependencies are separated into base, development, and production requirement files. Ruff and pytest configuration lives in `pyproject.toml`.
