# Kuzenga Canonical Backend Architecture

- **Status:** `kuzenga/` is the authoritative Django project for the owner-authorized Phase 1 consolidation. The broader target/deployment architecture and ADR remain proposed pending explicit owner approval.
- **Related:** [Comparative audit](backend-comparative-audit.md), [consolidation plan](backend-consolidation-plan.md), [ADR-0001](decisions/0001-canonical-backend.md)
- **Evidence reviewed:** `kuzenga/README.md`, `backend/README.md`, `backend/ARCHITECTURE.md`, existing application/settings/tests, and the central Kuzenga rules.

## 1. Recommendation

Preserve `kuzenga/` as the canonical Django application and consolidate approved infrastructure from `backend/` into it. `kuzenga/` already owns the custom user, tenant/membership authorization, business models/services, migration history, and the Django template/HTMX frontend. `backend/` currently owns only foundation concerns: DRF configuration, PostgreSQL-first settings, a DB-aware health view, and Docker patterns. Selecting `backend/` as the canonical project would require porting the product, identity, tenant boundary, UI, and schema into an empty project, increasing migration and regression risk.

The project owner has explicitly authorized Phase 1 consolidation into `kuzenga/`. The separate `backend/` project remains intact as a temporary reference. This does not approve every later deployment, data migration, security-policy, or infrastructure decision described below.

## 2. Target architecture

One deployable Django modular monolith, one project settings package, one authoritative database schema/migration graph, one custom identity model, and one frontend stack. Django templates, HTMX, and Tailwind remain first-class presentation paths. DRF is an additional transport layer within this same Django project; it does not become a separate service.

```text
Browser
  ├── Django templates + HTMX ──────────────┐
  └── approved JSON clients -> DRF API      │
                                             v
Single Django/Gunicorn application (kuzenga/)
  ├── Authentication and request middleware
  ├── Tenant context and backend permissions
  ├── Domain apps: core, accounts, tenancy,
  │   academics, students, attendance, ...
  ├── Domain services and transaction boundaries
  └── PostgreSQL
       └── Redis broker/cache -> Celery workers

Production edge: Nginx or managed ingress -> Gunicorn
Local/CI: Docker Compose; CI: GitHub Actions (proposed)
```

Nginx is appropriate when the deployment needs a self-managed reverse proxy, TLS termination, static asset delivery, or request limits. If a managed ingress already provides those functions, do not add another proxy tier. Do not introduce microservices for the listed workloads.

## 3. Application boundaries and responsibilities

| Area | Target responsibility |
|---|---|
| `apps.core` | Shared base models, tenant context primitives, carefully scoped shared forms/utilities, and security audit abstraction. Avoid becoming a second domain app. |
| `apps.accounts` | Global `AUTH_USER_MODEL` and identity lifecycle. Keep school membership and school roles in tenancy. |
| `apps.tenancy` | Tenant lifecycle, memberships, tenant resolution, role/permission policy, module entitlements, and explicit platform-admin access. |
| `apps.academics` | Existing academic years, terms, grades, classes, and subjects. Keep academic policy in approved service/model boundaries. |
| `apps.students` | Existing student, guardian, enrolment, and admission-number behavior. Preserve tenant ownership and history. |
| `apps.attendance` | Existing register/session workflow and attendance records. Keep write workflows transactional and tenant-scoped. |
| Django templates/HTMX | Existing authenticated school UI, server validation, messages, and partial responses. Preserve routes and visual language. |
| DRF | JSON serialization, request validation, routing, and transport-specific permissions. Delegate business rules to existing domain services. |
| Celery tasks | Only approved asynchronous work. Tasks establish tenant and actor context explicitly, are idempotent, and call domain services rather than duplicating business rules. |

Admissions, finance, examinations, communication, and reporting remain pending specification. Do not create models or workflows for them as part of consolidation.

## 4. Classification of current applications and files

Classification meanings: **RETAIN** = keep as the canonical capability; **IMPROVE** = keep and harden/refactor; **INTEGRATE** = incorporate selected behavior/patterns from `backend/`; **REPLACE** = replace a current implementation after equivalent behavior and migration are approved; **DEPRECATE** = stop using after a successful, reviewed transition. Classifications describe a future plan, not current changes.

### 4.1 Existing product project: `kuzenga/`

| Existing app/file | Classification | Reason and intended treatment |
|---|---|---|
| `apps/accounts/` and its migrations | **RETAIN** | It owns the configured custom email user model. Preserve identity, primary keys, password hashes, and migration dependency; do not create another user model. Improve manager/admin invariants only in an approved hardening phase. |
| `apps/tenancy/` | **IMPROVE** | Retain tenant, membership, roles, entitlements, and access flow. Strengthen deny-by-default authorization, platform-admin policy, audit, tenant lifecycle validation, and API/background context. |
| `apps/core/` | **IMPROVE** | Retain tenant context, scoped base models, forms, and audit concepts. Close explicit-tenant/no-context and bulk-write bypasses; define audit consistency and error handling. |
| `apps/academics/` | **RETAIN** | Keep existing domain models and UI. Review model-level invariants and query patterns when PostgreSQL is adopted. |
| `apps/students/` | **RETAIN** | Keep student, guardian, enrolment, and admission-number models/services. Preserve admission numbering and history; add approved integrity and security controls. |
| `apps/attendance/` | **RETAIN** | Keep the daily register workflow and tenant-scoped relationships. Review concurrent register opening/submission and state invariants. |
| App `migrations/` directories | **RETAIN** | Preserve the existing migration graph as the only product schema history. Do not squash/reset/recreate as a shortcut. |
| `apps/tenancy/management/commands/` | **IMPROVE** | Retain catalogue/provisioning capabilities, but replace unsafe credential handling and add explicit checks/auditing before production use. |
| `apps/*/admin.py` | **IMPROVE** | Preserve useful Django admin. Formalize the platform-only unscoped access boundary, permissions, and audit trail. |
| `apps/academics/views.pyy` | **DEPRECATE** | It is an identical, non-imported duplicate of `views.py`. Confirm no external tooling depends on it, then remove only under a separate cleanup approval. |
| `config/settings/base.py` | **IMPROVE** | Keep the current project as settings owner. Integrate `django-environ`/PostgreSQL-first patterns and structured logging; remove unsafe production fallback only after environment rollout is prepared. |
| `config/settings/development.py` | **IMPROVE** | Preserve convenient local development while isolating local-only defaults from production. |
| `config/settings/test.py` | **IMPROVE** | Keep fast isolated tests, and add a PostgreSQL-backed CI/integration test profile to cover real engine behavior. |
| `config/settings/production.py` | **IMPROVE** | Retain HTTPS/cookie/HSTS controls; fail closed on missing secret, host, database, proxy, and storage configuration. |
| `config/urls.py` | **INTEGRATE** | Remains the canonical router. Add an approved DRF API include and preserve existing template route names and health behavior. |
| `config/wsgi.py`, `config/asgi.py`, `manage.py` | **RETAIN** | Keep the existing project's runtime entry points; use one settings/package authority. |
| `requirements/base.txt` | **IMPROVE** | Make this the single canonical runtime dependency declaration; merge only needed DRF, environment, PostgreSQL, Redis/Celery, and Gunicorn dependencies after review. |
| `requirements/development.txt`, `requirements/production.txt` | **IMPROVE** | Keep environment-specific groups, align supported versions, and add a reproducible lock/constraints strategy. |
| `pyproject.toml` | **IMPROVE** | Keep one authoritative pytest/Ruff configuration for the product project and extend it for API/coverage checks. |
| `templates/`, `static/` | **RETAIN** | Preserve template, HTMX, Tailwind, and existing design behavior. Replace production CDN use with a reviewed build/vendor path without a UI rewrite. |
| `tests/` | **IMPROVE** | Retain existing tenant/access/workflow coverage and expand it for PostgreSQL, API permissions, migrations, audit, and background tasks. |
| `docker-compose.yml` | **REPLACE** | Replace the DB-only local stack with a unified, reviewed Compose definition for the canonical app, PostgreSQL, Redis, and Celery. Do not treat local Compose as a production deployment. |
| `.env.example` | **IMPROVE** | Keep one canonical example. Use fake values and require PostgreSQL-oriented variables; never copy actual `.env` secrets. |
| `.gitignore` | **IMPROVE** | Keep one source of truth and verify it excludes environments, local DBs, media, static build output, and test artifacts. |
| `README.md` | **IMPROVE** | Keep project setup and module notes; update only after actual target changes and decision approval. |

### 4.2 Infrastructure project: `backend/`

| Existing app/file | Classification | Reason and intended treatment |
|---|---|---|
| `core/views.py`, `core/urls.py` | **INTEGRATE** | Port the DB-aware health/readiness behavior into the canonical router, preserving a coarse public response and defining liveness versus dependency readiness. |
| `core/tests/test_health.py` | **INTEGRATE** | Merge health behavior coverage into the canonical suite; add PostgreSQL service coverage in CI. |
| `config/settings/base.py` | **INTEGRATE** | Use as a reference for environment parsing, explicit PostgreSQL URL, static/media roots, and console logging; adapt to existing app settings/middleware rather than wholesale replacement. |
| `config/settings/development.py`, `testing.py`, `production.py` | **INTEGRATE** | Port appropriate environment split and production checks into `kuzenga/config/settings/`; do not retain two independently changing settings sets. |
| `config/urls.py` | **INTEGRATE** | Reuse the DRF include pattern in `kuzenga/config/urls.py`; do not run a separate API router/runtime. |
| `manage.py`, `config/wsgi.py`, `config/asgi.py` | **DEPRECATE** | They are duplicate runtime entry points. After successful canonical cutover, stop invoking this project. Preserve files until owner-approved archival/cleanup. |
| `requirements/*.txt`, `pyproject.toml` | **INTEGRATE** | Merge required packages and test/lint settings into the canonical manifests, resolve versions once, then stop maintaining duplicate manifests. |
| `Dockerfile` | **INTEGRATE** | Adapt the non-root Python/Gunicorn image pattern to the canonical source root, production settings, static collection, health checks, and deterministic dependency installation. |
| `docker-compose.yml` | **INTEGRATE** | Reuse PostgreSQL health gating and service dependency pattern. Redesign for canonical app plus Redis/Celery; current Compose explicitly selects development settings and is not production-ready. |
| `.env.example` | **INTEGRATE** | Merge variable names/documentation into the single canonical example; do not bring along placeholder values as operational secrets. |
| `.gitignore` | **INTEGRATE** | Merge any missing relevant ignores into the canonical ignore policy. |
| `README.md`, `ARCHITECTURE.md` | **DEPRECATE** | Preserve as historical references during transition. After target behavior is incorporated into canonical docs, mark them superseded and retire the standalone project only with owner approval. |
| `core/apps.py`, `core/__init__.py`, project settings package files | **DEPRECATE** | Infrastructure-only app/package belongs to the standalone project. Port only the health capability/configuration; do not introduce a second `core` app in the product. |

### 4.3 New target files (not present today)

No CI workflow exists. A later approved change may add `.github/workflows/` for lint, tests on PostgreSQL, migration checks, dependency/security scanning, and image build. Deployment jobs require separate environment/approval design. Add Celery app/task modules and Nginx configuration only when their operations and deployment boundaries have been approved. These are proposals, not files created in this task.

## 5. Database architecture and migration safety

### Production database

- Use one PostgreSQL database for the canonical Django application. Production must fail fast when `DATABASE_URL`/required connection components are absent; SQLite remains a local/test convenience only where explicitly selected.
- Separate application DB credentials from migration/administration credentials where the deployment platform supports it. Restrict network access to app, worker, and approved operator paths; encrypt connections where required by hosting.
- Django migrations remain the authoritative schema history. Preserve `accounts.User` as the configured custom user and preserve all current app migration dependencies.
- Redis is not a source of truth. It may serve Celery broker/cache roles after persistence, availability, access control, and retention are defined.

### Models, relationships, and tenant isolation

- Keep existing models and relationships; do not recreate schema from model snapshots.
- Tenant-owned rows remain scoped by tenant. Existing Python checks and scoped managers must be complemented by reviewed write-path rules and, where feasible, database constraints that prevent relationships crossing tenants.
- Do not weaken tenant scope for serializers, admin, workers, exports, or bulk operations. Explicit platform access must be permission-checked and audited.
- Add indexes based on observed filters/joins and query plans; avoid speculative duplicates. Review `tenant_id` and common tenant-scoped access patterns during PostgreSQL verification.
- Use atomic transactions for multi-row domain workflows. Define concurrency behavior for admission sequences and attendance session creation/submission; verify with PostgreSQL because SQLite does not provide equivalent locking behavior.
- Backup, restore, retention, encryption, RPO/RTO, and point-in-time recovery require a named operational owner and approved objectives. No objectives are assumed here.

### Migration and data cutover

1. Inventory current migration graph and database state without changing it. Determine whether any production data exists and identify its database engine; the repository's local SQLite file is not presumed production data.
2. Back up and rehearse a restore before any production database operation. Validate source and target schema and row counts.
3. Provision PostgreSQL and apply existing migrations in order; do not reset or delete migration files/tables. Test from an empty PostgreSQL database and from a representative existing backup.
4. If SQLite data must be retained, build a separately reviewed export/import plan preserving PKs, user password hashes, tenant memberships, foreign keys, UUIDs, timestamps, and sequence state. Validate referential integrity and tenant ownership after import.
5. Prefer a single controlled write freeze and cutover. Do not dual-write both Django projects or allow them to mutate the same records concurrently.
6. Rehearse rollback to the known-good application/database snapshot. Any destructive migration requires explicit owner review, documented data recovery, and a safe rollback/forward-fix decision.

## 6. Security architecture

- **Identity:** retain `accounts.User` as the sole global user model. Continue to separate global authentication from tenant membership/role. Maintain Django password hashing and validators; define MFA/recovery/rate-limit policy before claiming full production readiness.
- **Browser sessions:** keep Django session authentication, CSRF middleware/tokens, HTTPS, secure session/CSRF cookies, trusted hosts, and explicit reverse-proxy configuration. Do not exempt HTMX/browser writes from CSRF.
- **DRF:** default new API views to authenticated access. Public health endpoints must explicitly opt in. Require explicit object/action permissions and tenant-scoped querysets; serialize only fields the caller can read. Do not rely on frontend visibility.
- **Tenant context:** middleware resolves tenant from the authenticated server-side session and active membership. API and Celery requests/tasks must verify membership/context per operation; never trust client tenant IDs on their own. Negative cross-tenant tests cover list, detail, nested, bulk, export, and async operations.
- **RBAC:** use one server-side permission source and map roles to explicit actions. Review the broad owner wildcard and Django admin bypass as privileged capabilities. Platform access is narrow, explicitly granted, and audited.
- **Data integrity:** harden model/service/queryset bulk paths and related-object checks. Tenant boundary checks must cover writes, not only row reads.
- **Sensitive data:** minimize student PII in logs; redact credentials/tokens; restrict export/download access and retention. Audit sensitive reads/exports where product/privacy policy requires it.
- **Audit:** centralize event recording for security-critical state changes. Application append-only behavior is not tamper-proof by itself; define DB permissions, retention, and operational protections.
- **Secrets:** use environment/secret manager injection per environment. Commit only placeholders. Never use the provisioning password CLI argument pattern in a production flow.
- **Uploads:** before adding upload behavior, define size/type/content validation, storage isolation, private serving, malware controls, and retention. No upload design is assumed.

## 7. API and frontend integration

Keep one Django project and route surface. Preserve current named template routes and HTMX partial behavior. Introduce DRF under a reviewed API prefix such as `/api/v1/` only after route/version compatibility is approved. Django templates continue calling Django views/forms; approved HTMX interactions remain same-origin and use session+CSRF semantics. JSON clients call DRF endpoints that invoke the same domain services and use the same membership, permissions, and tenant scope.

Avoid duplicated validation/business rules: serializers validate transport input, domain services enforce workflow rules, and models/database constraints protect invariants. Define response and error formats, pagination, authentication/client types, and deprecation compatibility before exposing endpoints. Build and vendor the existing Tailwind/HTMX assets for production while keeping the current visual system; no SPA or frontend rewrite is proposed.

## 8. Runtime and deployment target

- **Application:** one non-root Docker image for the canonical Django project, Gunicorn workers, environment-selected production settings, bounded worker/timeouts, and application health checks.
- **PostgreSQL:** persistent managed/Compose database with readiness checks and backup/restore policy. Compose database credentials come only from uncommitted environment/secret injection.
- **Redis/Celery:** Redis service and worker container share the same application image/dependencies. Add beat only if approved scheduled tasks exist. Health checks and graceful shutdown/retry semantics are required.
- **Nginx/ingress:** TLS termination, forwarding headers, request-size limits, rate controls, and static delivery at Nginx or managed ingress. Configure Django proxy trust only for known infrastructure.
- **Static/media:** `collectstatic` produces immutable static artifacts served by Nginx/CDN/object storage. User uploads require private/persistent storage; do not rely on ephemeral app-container disks.
- **Logging:** structured logs to stdout for aggregation, request/correlation IDs, separate security/audit events, safe redaction, and appropriate retention. Do not log credentials or unnecessary student data.
- **CI:** proposed GitHub Actions checks: Ruff, tests, PostgreSQL-backed integration tests, migration consistency, dependency/security scanning, and Docker build. Production deploys require protected environments and human approval; no workflow is added by this proposal.

## 9. Non-goals and open decisions

This target does not specify new admissions, finance, examinations, communications, or reporting requirements; select a token/MFA provider; set backup retention or recovery objectives; mandate self-hosted Nginx; create public APIs beyond the existing health endpoint; or authorize migration, cleanup, or deployment. These require explicit owner/product decisions and, where appropriate, a follow-up ADR.
