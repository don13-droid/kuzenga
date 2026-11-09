# Kuzenga Backend Comparative Architecture Audit

- **Status:** Audit findings and recommendation; not an approved architecture decision.
- **Date:** 2026-11-04
- **Scope:** Read-only inspection of `kuzenga/` and `backend/`, including settings, apps, models, auth/permissions, tenant controls, routes/templates, dependencies, tests, migrations, Docker files, and project documentation.
- **Sensitive files:** `.env` files were not read. Only committed-style example configuration was inspected.

## 1. Executive summary

The repository currently contains two independent Django projects with different responsibilities and configuration:

- [`kuzenga/`](../../kuzenga/README.md) is the existing product modular monolith. It has a custom email-based user, shared-schema tenant membership and access controls, subscription entitlements, academics, student, and attendance domains, server-rendered Django/HTMX screens, migrations, and 21 configured tests.
- [`backend/`](../../backend/README.md) is an infrastructure-only Django REST Framework project. It has environment-based settings, PostgreSQL configuration, one database-aware health endpoint, one test, and a web-plus-PostgreSQL Compose stack. It has no business models, custom authentication, tenant support, or integration with the existing UI.

They overlap as standalone Django runtimes but do not yet duplicate business models or endpoints. Running both as peer application backends would create two sources of truth for configuration, schema, authentication, and future APIs. The application with product behavior is `kuzenga/`; the infrastructure foundation is `backend/`.

**Recommendation for owner review:** designate `kuzenga/` as the near-term canonical application backend and consolidate the useful infrastructure patterns from `backend/` into that modular monolith through a reviewed, staged plan. Keep DRF as an API layer within the same Django project if an API is approved; do not operate two competing backends. This recommendation is based on existing product functionality and frontend coupling, not an existing approval. Do not consolidate until the owner approves the canonical-project decision and migration plan.

The most important risks are incomplete enforcement of tenant invariants outside ordinary request/form paths, DRF's global `AllowAny` default in `backend/`, SQLite fallback and weaker production configuration in `kuzenga/`, and the absence of verified production deployment, PostgreSQL, and CI evidence.

## 2. Architecture of each project

### 2.1 `kuzenga/`: product modular monolith

- Django 5.2 settings are split into base, development, test, and production modules. `manage.py` defaults to development settings.
- `INSTALLED_APPS` includes `core`, `accounts`, `tenancy`, `academics`, `students`, and `attendance`, alongside Django contrib apps.
- The UI is Django templates with HTMX partial responses and Tailwind loaded from CDNs. URL routes cover dashboard, tenant selection, academics, students, attendance, login/logout, admin, and a basic health route.
- There is no DRF installation, serializer layer, or JSON API architecture in this project.
- `accounts.User` is a custom global identity (`AbstractBaseUser` and `PermissionsMixin`) using email as `USERNAME_FIELD`. School access is represented separately by `tenancy.Membership`.
- Tenant isolation uses a shared-schema `Tenant` model, a session-selected active tenant, request middleware, `ContextVar` tenant state, `TenantScopedModel`, tenant-filtering managers, tenant-aware forms, role permissions, and module entitlements.
- Domain models cover academic years/terms/grades/classes/subjects; students/guardians/enrolments/admission sequences; attendance sessions/records; and tenant subscriptions/entitlements. Core also contains audit events.
- Multi-write student, attendance, and subscription service workflows use `transaction.atomic()`. Existing migrations are app-based and include generated constraints and indexes.
- Local and test databases default to SQLite. The example `.env` also configures SQLite. `DATABASE_URL` can select PostgreSQL, but production settings do not require PostgreSQL.
- Production settings enable HTTPS redirect, secure session/CSRF cookies, HSTS, and a forwarded-proto header. The project has no app Dockerfile/service; its Compose file only starts a local PostgreSQL container with hard-coded development credentials.
- README calls out pre-production work: compile/vendor frontend assets, PostgreSQL, Redis/Celery, object storage, Docker/CI, and production secrets.

### 2.2 `backend/`: API infrastructure foundation

- A separate Django 5.2 project with shared, development, testing, and production settings using `django-environ`.
- Installed apps are Django contrib, DRF, and an infrastructure-only `core` app. It does not set `AUTH_USER_MODEL` or define a business model, migration, authentication flow, permission registry, or tenant context.
- DRF is configured for JSON rendering/parsing. Its default permission class is `AllowAny`; the only route is a public `GET /api/health/` view which ensures a DB connection and responds with 200/503.
- Runtime database configuration is PostgreSQL via `DATABASE_URL`; testing overrides to in-memory SQLite. Timezone-aware operation is enabled. Static and media roots and console logging are configured.
- Production settings require a non-placeholder secret and non-empty allowed hosts, and configure secure cookies, HTTPS redirect by default, HSTS, content-type protection, frame denial, and a proxy HTTPS header.
- The Dockerfile uses Python 3.12 slim, installs production requirements, and runs Gunicorn as a non-root user. Compose starts PostgreSQL and the web service, waits on PostgreSQL health, applies migrations at web startup, and runs Gunicorn. Compose explicitly selects development settings, so it is a local stack, not a production deployment definition.
- One health endpoint test is configured with SQLite. No domain or integration tests exist yet.

## 3. Comparative technical assessment

| Area | `kuzenga/` | `backend/` | Assessment |
|---|---|---|---|
| Product domains | Six apps including core/accounts/tenancy and three business domains | Infrastructure `core` only | Existing product capability resides in `kuzenga/` |
| Identity | Custom email identity and Django session login | Django default auth installed, no configured custom user or auth flow | A future move must preserve the custom user table and authentication semantics |
| Authorization | Role permission registry plus route decorators and entitlement checks | DRF global `AllowAny`; health explicitly public | Backend API defaults are unsafe for adding protected endpoints |
| Tenancy | Shared-schema tenant membership and request/context scoping | None | Tenant security must be designed before moving business endpoints into `backend/` |
| Persistence | SQLite by default; optional URL-based DB and migrations | PostgreSQL-first runtime; SQLite test DB; no app schema | Conflicting database defaults and two settings sources |
| API | Server-rendered views/forms; no DRF | DRF JSON health route only | No established business API contract to migrate |
| Frontend | Django templates, HTMX, Tailwind | None | Existing frontend is tightly coupled to `kuzenga/` views, context, URLs, and sessions |
| Tests | 21 tests across tenant isolation, access/entitlements, and MVP workflows | One health test | `kuzenga/` has broader domain/security coverage; neither test suite has demonstrated PostgreSQL integration here |
| Lint/dependencies | Requirements ranges, pytest/Ruff config | Separate requirements ranges, pytest/Ruff config | Duplicate dependency/configuration lifecycle; no lockfile observed |
| Containers | Database-only Compose with development credentials | Dockerfile and app+DB Compose | Useful app-container pattern in `backend/`, but Compose selects development settings |
| Deployment | Production flags exist; README lists significant gaps | More complete foundation, but no domain auth, app static/media serving, CI, or production Compose profile | Neither is deployment-proven or fully production-ready |

### Existing reusable functionality

If the owner selects `kuzenga/` as canonical, preserve the following product capabilities as the system of record:

- Custom user model, global identities, memberships, roles, active-tenant session selection, permission registry, and module entitlements.
- Fail-closed tenant query manager, tenant-aware model forms, service-level tenant workflows, and cross-tenant/authorization tests.
- Existing academic, student/guardian/enrolment/admission-number, and attendance models/services/templates.
- Existing migration history and data semantics. These must be inspected and preserved; they must not be regenerated or copied into a new project casually.

Reusable infrastructure ideas from `backend/` include environment parsing with `django-environ`, isolated settings modules, PostgreSQL-only runtime configuration, DRF JSON conventions, DB-aware health behavior, console logging, non-root image construction, database health gating, and dependency separation. Reuse the design only after owner approval; do not keep duplicate implementations active.

### Duplicated implementations and inconsistencies

- Two `manage.py` entry points, settings packages, Django dependency manifests, pytest/Ruff configurations, WSGI/ASGI applications, health routes, environment examples, and Compose definitions.
- The projects have separate Django app registries and databases by default. There is no shared `AUTH_USER_MODEL`, tenancy middleware/context, schema, API client, or deployment contract.
- `kuzenga/` has product UI and models but no DRF or containerized app; `backend/` has DRF and app containerization but no product/auth/tenant behavior.
- Database behavior is inconsistent: SQLite is the old application's default including its example environment; PostgreSQL is the new foundation's runtime default and Compose database.
- Backend test settings use SQLite, so the lone health test does not validate PostgreSQL driver, credentials, or network connectivity.
- `kuzenga/apps/academics/views.pyy` has the same hash and length as `views.py`; it is not a Python module Django imports but is a stale duplicate artifact that can confuse maintenance and tooling.

### API and frontend integration

The existing frontend submits Django forms and uses session authentication, CSRF tokens, template context processors, and HTMX partial rendering. The DRF project has no integration with those templates or sessions. Introducing `backend/` as an independently deployed API would require a deliberate decision on browser authentication, CSRF, CORS, session/cookie domain, API authorization, tenant context propagation, and client error/response contracts. No such contract is present.

## 4. Security assessment

Findings below are code/configuration observations, not penetration-test results.

| Priority | Finding | Evidence and impact |
|---|---|---|
| **High before API expansion** | DRF's global permission default is `AllowAny`. | `backend/config/settings/base.py` sets `DEFAULT_PERMISSION_CLASSES` to `AllowAny`. Today only the health endpoint exists and is intentionally public; a future endpoint that omits explicit protection would also be public. Establish deny-by-default API policy before adding business endpoints. |
| **High risk in tenant boundary** | Tenant invariants rely substantially on Python model `save()` and scoped-manager conventions. | `TenantScopedModel.save()` checks mismatches only when a current tenant context exists. An instance with an explicitly assigned tenant can be saved with no current context; `bulk_create`, `bulk_update`, and queryset `update()` bypass `save()` as its own docstring notes. Cross-tenant model relations are not represented as composite tenant-aware DB constraints. Current forms/views scope ordinary paths, but direct service/admin/bulk paths need controls and negative tests. |
| **High operational sensitivity** | Platform admin deliberately bypasses tenant query scoping. | `TenantScopedAdmin.get_queryset()` returns `self.model.unscoped.all()`. This is appropriate only for explicitly authorized platform operations; the code does not add tenant-specific auditing or a break-glass workflow around this broad view. Django admin permissions still apply. |
| **Medium** | Old project does not enforce PostgreSQL or strict production configuration at startup. | `kuzenga/config/settings/base.py` falls back to SQLite; production settings only reject the exact development secret string and do not explicitly require `ALLOWED_HOSTS` or a PostgreSQL engine. Empty/misconfigured values can therefore bypass the intended fail-fast checks or leave the app unavailable. |
| **Medium** | Development asset CDNs are still in the base template path. | `kuzenga/templates/base/base.html` loads Tailwind from `cdn.tailwindcss.com` and HTMX from an unpinned `unpkg.com` URL without SRI. The template labels these development-only and README says to vendor before production, but settings do not prevent production use. This is supply-chain and availability exposure if the production checklist is skipped. |
| **Medium** | Provisioning accepts an owner password as a command-line argument. | `kuzenga/apps/tenancy/management/commands/provision_tenant.py` requires `--password`; command arguments may be exposed through shell history/process inspection. It also attaches an existing email account to the new tenant as owner without re-authentication/confirmation, a sensitive operational action. |
| **Medium** | Abuse and authentication hardening are not demonstrated. | No throttling/rate-limit package or MFA is configured in either project. The old project has Django password validators and session/CSRF support, but no recovery/MFA flows or explicit login throttling were found. |
| **Medium** | Audit coverage and append-only guarantees are partial. | Audit records exist and selected student/enrolment/attendance/subscription workflows record events. Tenant/membership/admin actions and many mutations are not consistently recorded. Immutability is enforced through `save()` and admin UI, not at the DB permission/trigger level; bulk updates/deletes can bypass it. |
| **Low/current scope** | Backend health is intentionally unauthenticated. | The route returns only coarse service and DB status and catches `DatabaseError`; this is appropriate for a basic health endpoint. Avoid adding configuration or infrastructure details. |

Positive controls observed in `kuzenga/`: CSRF middleware and template tokens are present; session auth uses Django; active membership and tenant status are revalidated per request; tenant querysets fail closed without context; cross-tenant student IDs are intended to return 404; views use access decorators; forms scope tenant-owned FK choices; tenant-scoped writes check related tenant ownership; and tests cover multiple cross-tenant and authorization scenarios. These reduce common application-path exposure but do not eliminate the bypass paths above.

`backend/` production flags are stronger than the old project's, but its DRF authorization default and absence of auth/tenant services make it unsuitable for school data until those boundaries are implemented and tested.

## 5. Infrastructure assessment

- **PostgreSQL:** configured as an optional URL in `kuzenga/`; Compose starts only a database and uses static development credentials. `backend/` uses PostgreSQL as runtime DB and provides a Compose DB with health check, but actual connection was not tested in this audit environment.
- **Migrations:** the existing product project has migration history across its apps, including cross-app dependency ordering. `backend/` has no application-owned schema migration. No destructive operation was observed in the inspected current migrations; this does not replace a full migration-history review before consolidation.
- **Static/media:** `kuzenga/` configures static collection but no media settings. `backend/` defines static/media roots but does not collect static assets or configure persistent/production media storage. Neither audit observed a production static/media serving path.
- **Background tasks:** no Celery/Redis/task queue implementation was found. The existing README lists Redis/Celery as pre-production work.
- **Logging/observability:** `backend/` defines console logging. `kuzenga/` has no project logging configuration and largely relies on Django defaults; no metrics, tracing, or error-reporting integration was found.
- **Docker:** `backend/` has the reusable application-image pattern and runs as non-root. Compose sets `DJANGO_SETTINGS_MODULE=config.settings.development`; `development.py` unconditionally sets `DEBUG = True`. It is suitable as a local stack, not a production stack. The app service has no health check, and migrations run on every web container start.
- **CI/CD:** no GitHub Actions workflows or other CI/deployment pipeline were found. Branch protection, security scans, dependency auditing, staging, production approvals, backup, and rollback behavior are unverified.
- **Dependency reproducibility:** both projects use bounded but non-exact requirement ranges and no lock/constraints file was observed. Dependency versions can drift between installs/builds.

## 6. Risks and technical debt

1. **Competing project authority:** future development may add identical domains, settings, users, or migrations to either project, creating irreconcilable sources of truth.
2. **Tenant security escape paths:** manager/context conventions do not enforce every write path. Explicit tenant assignment without context, admin bypasses, bulk writes, background tasks, and future APIs need explicit handling.
3. **Identity and migration coupling:** `kuzenga/` already has `AUTH_USER_MODEL = "accounts.User"` and migrations that depend on it. A move or separate API cannot safely switch user models after schema creation or casually transplant migration files.
4. **Database drift:** one project defaults to SQLite and the other to PostgreSQL. SQLite test behavior does not cover PostgreSQL locking, constraints, SQL, or transaction behavior.
5. **Frontend coupling:** existing templates depend on `request.tenant`, tenancy context processors, Django messages, URL names, and session auth. Splitting the API would break these implicitly unless a new contract is designed.
6. **Authorization maintenance:** old project route protections are decorators and role strings; a new API must map these consistently and test list/detail/action permissions. There is no shared API permission base yet.
7. **Operational security:** local credential defaults, command-line provisioning password, CDN runtime dependencies, lack of app health checks/CI, and incomplete deployment controls raise risk if development setup is promoted without a separate hardening review.
8. **Model integrity gaps:** tenant consistency is checked in Python rather than fully encoded in database relations; enrolment date overlap, exactly-one-current-academic-year, and related domain invariants are not comprehensively constrained in the inspected models.
9. **Documentation/build drift:** README setup and pre-production requirements are useful but no central runbook or production deployment configuration was found. The duplicate `.pyy` view artifact adds avoidable ambiguity.
10. **Audit completeness:** sensitive operations do not share one consistently enforced audit policy, and current append-only behavior is application-level rather than tamper-resistant.

## 7. Recommended canonical backend architecture

**Recommendation (proposed, pending owner approval):** use `kuzenga/` as the single canonical application backend and modular monolith in the near term. It is the only project with business data, custom identity, tenant isolation, authorization, migrations, tests, and a working frontend integration. Treat the current `backend/` as an infrastructure prototype/reference, not a second production application.

Within the canonical project, keep one Django runtime and database with cohesive domain apps. If DRF is approved, add it as an API transport layer in that project, reuse the same user, tenant context, domain services, and authorization rules, and default new endpoints to authenticated/explicit permissions. Keep the existing template/HTMX UI until an owner-approved frontend decision changes it.

This is an audit recommendation, not an ADR or permission to consolidate. The owner could instead select `backend/`; that option is feasible only as a controlled port of all product modules, identity, tenancy, UI integration, and migration history before it serves school traffic.

## 8. Proposed consolidation strategy

No consolidation has been performed. If the owner accepts the recommendation, use gated phases:

1. **Decide and record:** approve the canonical project, deployment shape, frontend/API relationship, and source-of-truth database in an ADR. Freeze new domain work in the non-canonical project during the transition.
2. **Inventory and baseline:** record migration graph, schema/data counts, custom-user IDs/password hashes, tenant memberships, business invariants, routes, permissions, templates, and current test behavior. Verify source and target backups/restores before any data operation.
3. **Harden the selected project first:** require PostgreSQL and production secrets/hosts, define deny-by-default API permissions, close tenant write bypasses, define platform-admin policy/auditing, configure production static/media/logging/health checks, and add CI gates. This is implementation work requiring separate approval.
4. **Port infrastructure without parallel runtime:** adopt reviewed settings/logging/container patterns in the chosen project while retaining one database/schema and one migration graph. Do not copy user/tenant models into a second app or run duplicate auth.
5. **Integrate transport incrementally:** expose approved DRF endpoints over existing domain services and permissions. Keep session/CSRF behavior explicit for browser clients; add endpoint and tenant-isolation tests before enabling each route.
6. **Data/migration plan if project directory changes:** use explicit forward migrations or a rehearsed data-transfer plan; preserve primary-key/user identity relationships and password hashes, verify row counts/FKs/tenant ownership, rehearse rollback, and obtain review before any destructive step. Do not delete the former project until production traffic and restore/rollback objectives are met.
7. **Retire by owner approval:** after acceptance criteria pass, make the non-canonical project read-only or archive it under a separately approved change. Do not keep two writable systems as an indefinite bridge.

## 9. Decisions requiring project-owner approval

1. Which project is canonical: recommended `kuzenga/`, or `backend/` after a full product port?
2. Whether the frontend remains Django templates/HTMX in the same modular monolith and whether/when DRF APIs are required.
3. Canonical production PostgreSQL database, migration ownership, and data migration/rollback authority.
4. Tenant enforcement strategy, including database-level relationship integrity, service/background-task context, permitted platform-admin bypasses, and audit requirements.
5. Authentication hardening scope: rate limiting, MFA/recovery, platform staff access policy, and provisioning credential flow.
6. Production operations: Docker deployment target, static/media storage, logging/monitoring, backups/restore objectives, CI/CD platform, staging, approvals, and rollback procedure.
7. Product/module invariants that are currently not constrained, such as enrolment overlap and academic-year current-state rules.

## 10. Audit checks and limitations

- `python -m ruff check .` passed in both project directories.
- `backend/`: `python -m pytest -q` passed (1 test); `python manage.py check --settings=config.settings.development` passed.
- `kuzenga/`: test and Django system checks could not initialize because `dj-database-url` is declared in `requirements/base.txt` but is not installed in the active audit Python environment. The audit did not install dependencies or alter the environment.
- Test inventory in source: 21 tests in `kuzenga/tests/`; 1 in `backend/core/tests/`.
- Python available in the audit environment was 3.15.2. Docker, `psql`, and `pg_isready` were unavailable, so container startup, PostgreSQL connection, PostgreSQL migrations, and production runtime behavior were not verified.
- This was a source/configuration audit, not a penetration test, full schema-data verification, or production deployment review. No code, model, migration, file location, or Docker configuration was changed.
