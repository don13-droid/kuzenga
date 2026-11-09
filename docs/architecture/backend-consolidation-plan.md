# Kuzenga Backend Consolidation Plan

- **Status:** Proposed implementation sequence; no phase is authorized by this plan alone.
- **Canonical target:** `kuzenga/` for the owner-authorized Phase 1; the full ADR remains proposed pending explicit acceptance.
- **Architecture:** [Canonical backend architecture](canonical-backend-architecture.md)
- **Rules:** Follow root `AGENTS.md`, `.codex/rules/`, and applicable module rules during every approved implementation phase.

## Phase 1 implementation status

The project owner has authorized the initial infrastructure consolidation in `kuzenga/`. Implemented in this phase: environment-based settings using `django-environ`; production PostgreSQL enforcement while retaining the existing SQLite local default; DRF with session authentication and authenticated-by-default permissions; a DB-aware public health implementation on the existing route plus an API alias; centralized console logging; static/media roots; pinned dependency constraints; a non-root Gunicorn Docker image; and a local PostgreSQL-backed Compose development stack. The custom user and existing migration files remain unchanged.

Redis, Celery, Nginx, production deployment automation, CI/CD, tenant-boundary refactoring, and production data conversion are not included in Phase 1. Docker/PostgreSQL execution is pending an environment with those services. `backend/` remains present as a temporary reference. The ADR remains `PROPOSED`; Phase 1 authorization does not mark the full architecture decision approved.

## 1. Guardrails

- Keep `kuzenga/` as the only product/schema/user/tenant source of truth after the owner approves the decision.
- Keep both project directories intact until phased acceptance criteria are met. No file moves, deletes, migration resets, or dual-write period is assumed.
- Use one database schema and one migration graph. Preserve `accounts.User`, IDs, password hashes, and existing relationships.
- Make each phase reviewable and reversible. Stop on data mismatch, tenant-isolation failure, migration drift, or security regression.
- No business requirements are inferred for planned modules. Redis/Celery infrastructure must not introduce unapproved background workflows.
- All destructive schema/data operations require explicit owner review, documented recovery, and a rehearsed restore.

## 2. File-by-file classification and migration map

See the classification meanings in the [canonical architecture](canonical-backend-architecture.md#4-classification-of-current-applications-and-files). This map identifies the future disposition of the files; it does not authorize changes now.

### Product project: retain as canonical (`kuzenga/`)

| Paths | Class | Planned action |
|---|---|---|
| `kuzenga/apps/accounts/**` | RETAIN | Keep `User` and existing migration as the sole identity schema. Review user-manager/admin invariants in a security phase. |
| `kuzenga/apps/tenancy/**` | IMPROVE | Keep tenant, membership, RBAC, entitlement, middleware, services, and management commands; harden platform access, audits, provisioning, and tenant context paths. |
| `kuzenga/apps/core/**` | IMPROVE | Keep shared tenant primitives, forms, audit, and health view; address unscoped/bulk write bypasses and extend health contracts. |
| `kuzenga/apps/academics/**` | RETAIN | Preserve domain behavior and migrations; review constraints and PostgreSQL query plans. |
| `kuzenga/apps/students/**` | RETAIN | Preserve student, guardian, enrolment, and admission sequence behavior; test concurrency and approved history invariants. |
| `kuzenga/apps/attendance/**` | RETAIN | Preserve register behavior; verify concurrent opens/submission and tenant-linked object integrity. |
| `kuzenga/apps/*/migrations/**` | RETAIN | Keep full migration history and dependencies. Add only forward migrations after separate approval/review. Never reset or replace with a fresh initial migration. |
| `kuzenga/config/settings/base.py` | IMPROVE | Establish required environment variables, PostgreSQL production enforcement, logging, static/media, and shared security settings. |
| `kuzenga/config/settings/development.py` | IMPROVE | Keep local developer behavior separate from production-only assumptions. |
| `kuzenga/config/settings/test.py` | IMPROVE | Retain isolated fast tests; add an explicit PostgreSQL integration profile/service for DB-specific behavior. |
| `kuzenga/config/settings/production.py` | IMPROVE | Retain secure defaults and fail fast on missing secret, allowed hosts, DB, trusted proxy, or required storage settings. |
| `kuzenga/config/urls.py` | INTEGRATE | Keep existing routes; incorporate DRF API routes and distinct readiness behavior without changing template names. |
| `kuzenga/config/wsgi.py`, `config/asgi.py`, `manage.py` | RETAIN | Preserve as the only application entry points. |
| `kuzenga/templates/**`, `kuzenga/static/**` | RETAIN | Keep existing Django/HTMX/Tailwind experience. Replace runtime CDN dependencies only through a separately tested asset-build phase. |
| `kuzenga/tests/**` | IMPROVE | Keep current test suite; add API, PostgreSQL, concurrency, tenant, audit, settings, and deployment checks as phases require. |
| `kuzenga/requirements/base.txt` | IMPROVE | Become sole runtime dependency list; add DRF, django-environ, Redis/Celery and any needed packages only with version/security review. |
| `kuzenga/requirements/development.txt`, `production.txt` | IMPROVE | Keep one environment-specific dependency split and establish repeatable dependency resolution. |
| `kuzenga/pyproject.toml` | IMPROVE | Keep one pytest/Ruff config and include approved integration checks. |
| `kuzenga/docker-compose.yml` | REPLACE | Replace DB-only local stack with reviewed canonical app+PostgreSQL+Redis+worker services. Keep production orchestration separate. |
| `kuzenga/.env.example`, `.gitignore` | IMPROVE | Keep one canonical example and ignore policy; require production PostgreSQL configuration and exclude all real `.env` files. |
| `kuzenga/README.md` | IMPROVE | Update run/test/deploy instructions after implementation, not before. |
| `kuzenga/apps/academics/views.pyy` | DEPRECATE | Verify references/tooling, then remove only in approved cleanup; it is identical to non-`.pyy` source. |

### Foundation project: selectively integrate, then deprecate

| Paths | Class | Planned action |
|---|---|---|
| `backend/config/settings/base.py` | INTEGRATE | Port selected env, PostgreSQL, logging, static/media, and DRF settings into `kuzenga/config/settings/base.py`; do not transplant as a replacement. |
| `backend/config/settings/development.py`, `testing.py`, `production.py` | INTEGRATE | Port useful split/security checks into matching existing settings modules. Keep one settings package. |
| `backend/config/urls.py` | INTEGRATE | Port only API route inclusion pattern into `kuzenga/config/urls.py`. |
| `backend/core/views.py`, `urls.py` | INTEGRATE | Adapt DB-aware health capability into canonical health/readiness routes. Preserve coarse public response. |
| `backend/core/tests/test_health.py` | INTEGRATE | Merge behavior into canonical tests and test DB failure/readiness paths. |
| `backend/Dockerfile` | INTEGRATE | Adapt non-root Gunicorn image pattern to canonical source and production static setup. |
| `backend/docker-compose.yml` | INTEGRATE | Reuse DB readiness gating; redesign for one canonical web service, PostgreSQL, Redis, and Celery. |
| `backend/requirements/**`, `backend/pyproject.toml` | INTEGRATE | Merge approved dependency/tool settings, resolve duplicates, then stop maintaining both manifests. |
| `backend/.env.example`, `.gitignore` | INTEGRATE | Merge variable/ignore requirements; do not copy real secrets or retain a second canonical config. |
| `backend/manage.py`, `config/wsgi.py`, `config/asgi.py` | DEPRECATE | Stop running the standalone application after cutover; preserve source until owner-approved archival. |
| `backend/README.md`, `ARCHITECTURE.md` | DEPRECATE | Preserve during transition; link/mark superseded only after canonical docs describe the implemented state. |
| `backend/core/apps.py`, `core/__init__.py`, duplicate project package | DEPRECATE | Do not add a competing product `core`; port only necessary health behavior/configuration. |

### New files proposed for later approved phases

| Path | Why/when |
|---|---|
| `.github/workflows/ci.yml` (name subject to repository convention) | Add after CI design approval; lint, tests, PostgreSQL integration, migration checks, dependency/security scan, image build. No deployment workflow is implied. |
| Canonical Celery app/task modules under `kuzenga/` | Add only when a real approved task needs background processing; do not create business jobs from infrastructure alone. |
| Nginx config/container, if self-managed edge is selected | Add only if hosting does not already provide TLS ingress, static delivery, and request controls. |
| Operational backup/restore documentation | Add after database provider, retention, encryption, and recovery objectives are approved. |

## 3. Phased implementation plan

### Phase 0 — Owner decision and baseline

- **Objectives:** Confirm the canonical project and deployment shape; establish source DB/data ownership; capture test, schema, migration, endpoint, and tenant-isolation baselines. Canonical `kuzenga/` ownership for Phase 1 is explicitly directed; production data and deployment details still need decisions.
- **Files affected:** ADR status/approval fields and audit follow-up only; no application changes.
- **Dependencies:** Project owner, product owner for module boundaries, operational owner for data/deployment facts.
- **Risks:** Incorrect assumptions about whether any database is production or contains authoritative data.
- **Required tests/checks:** Record current test/lint/system-check commands and results per project; list migration graph and schema without changing it; verify backup/restore process if real data exists.
- **Acceptance:** Owner explicitly accepts/rejects `kuzenga/` as canonical; data source and deployment ownership are recorded; baseline and known gaps are reviewed.
- **Rollback:** No runtime change. If the proposal is rejected, retain both projects and revise this plan/ADR.

### Phase 1 — Canonical security and configuration design (remaining hardening)

- **Objectives:** Complete security decisions beyond the initial settings integration: define tenant enforcement, platform admin policy, audit requirements, API client/auth modes, and production health/logging operations. Initial environment settings and authenticated-by-default DRF configuration are implemented.
- **Files affected:** Proposed later changes to `kuzenga/config/settings/*.py`, `apps/core`, `apps/tenancy`, `apps/accounts`, `config/urls.py`, `requirements`; tests under `kuzenga/tests/`. This phase begins only after Phase 0 approval.
- **Dependencies:** Phase 0; review from security and operations owners.
- **Risks:** Lockout, proxy/header mistakes, behavior differences between session UI and DRF, cross-tenant data exposure.
- **Required tests:** Settings fail-closed checks; authentication/CSRF; RBAC matrix; tenant positive/negative list/detail/write/bulk/admin tests; health behavior; no secret disclosure.
- **Acceptance:** Protected API behavior denies by default; tenant context cannot be forged; platform access is explicitly scoped/audited; local/dev/test/production settings have documented behavior.
- **Rollback:** Roll back application settings/permission release to prior version; keep stricter DB/data controls. Do not revert security controls in response to failed tests without owner/security review.

### Phase 2 — Dependency and settings convergence

- **Objectives:** Make `kuzenga/` the single dependency/settings authority; integrate DRF, django-environ, PostgreSQL driver/configuration, and logging. Keep dev/test/production distinct.
- **Files affected:** `kuzenga/requirements/*.txt`, `pyproject.toml`, `config/settings/*.py`, `.env.example`, `.gitignore`; use `backend/` equivalents as references only.
- **Dependencies:** Phase 1 decisions; tested dependency/version compatibility and secure secret provisioning.
- **Risks:** Import/config drift, unsupported version combinations, deploys unexpectedly using SQLite, missing environment values.
- **Required tests:** Install from clean environment; Django checks in all settings profiles; verify missing production DB/secret/hosts fail; ensure test settings are isolated; Ruff/pytest.
- **Acceptance:** One set of manifests/settings is authoritative; production selects PostgreSQL explicitly; no real `.env` is added to source control.
- **Rollback:** Revert dependency/settings commit independently; keep prior release and environment variables available. Do not migrate data until this phase passes.

### Phase 3 — DRF integration in the existing Django runtime

- **Objectives:** Add DRF to the same project, define API URL/response/permission/serializer conventions, and integrate health/readiness. Do not add unspecced domain endpoints.
- **Files affected:** `requirements/base.txt`, `config/settings/base.py`, `config/urls.py`, `apps/core` health implementation, API-focused tests in `kuzenga/tests/` or approved app test structure.
- **Dependencies:** Phase 1 security design and Phase 2 dependency convergence.
- **Risks:** Accidental anonymous endpoints, API bypass of domain services, CSRF/CORS/session mismatch, tenant query leaks.
- **Required tests:** API default-deny, explicit public health, authenticated session/CSRF behavior, permission denials, tenant-scoped list/detail, validation/error formats, DB readiness failure.
- **Acceptance:** Existing HTML routes and login flow remain unchanged; health check has clear liveness/readiness semantics; no business API ships before its module spec and tests.
- **Rollback:** Remove/disable the API include or feature routes while leaving existing template routes operational; keep DB schema unchanged in this phase.

### Phase 4 — PostgreSQL readiness and data plan

- **Objectives:** Verify all existing migrations and behavior on PostgreSQL; define and rehearse data conversion only if authoritative SQLite data must be preserved; close model/database tenant-integrity gaps using forward migrations.
- **Files affected:** Existing `kuzenga/apps/*/migrations/` only through separately reviewed new migrations; DB settings; test settings/profiles; data migration scripts only if approved and reviewed.
- **Dependencies:** Phases 0–2; confirmed source DB/data owner; PostgreSQL test service; tested backup and restore.
- **Risks:** Custom user and FK ID loss, migration locks, SQLite/PostgreSQL semantic differences, constraints rejecting existing data, tenant-crossing historical rows.
- **Required tests:** Migrate an empty PostgreSQL DB; migrate a representative copy; run full suite on PostgreSQL; validate counts, IDs, password hashes, FK integrity, tenant relationships, constraints, transaction/concurrency behavior; rollback/restore rehearsal.
- **Acceptance:** Existing migration graph applies forward; no reset/drop/recreate; discrepancies are resolved and signed off; measured runtime/locking and recovery are acceptable.
- **Rollback:** Stop cutover and restore verified backup. Use forward fixes for irreversible changes; any destructive step requires explicit owner approval and recovery evidence.

### Phase 5 — Tenant and domain invariant hardening

- **Objectives:** Strengthen tenant-safe model writes, bulk paths, relational consistency, membership changes, privileged admin access, audit coverage, admission sequence and attendance concurrency.
- **Files affected:** `apps/core/models.py`, `core/forms.py`, `core/admin.py`, `core/audit.py`; `apps/tenancy/{middleware,access,permissions,services,models,admin}.py`; affected domain models/services/admin; new forward migrations only if approved; `tests/test_tenant_isolation.py`, `test_access_and_entitlements.py`, `test_mvp_workflows.py`.
- **Dependencies:** Phase 1 approved policy and Phase 4 PostgreSQL test baseline.
- **Risks:** Breaking legitimate admin/management workflows, row lock behavior, historic data failing stricter constraints.
- **Required tests:** Cross-tenant saves and FKs with/without context; queryset/bulk updates; management tasks; role matrix; admin privileged access; concurrency; every touched module regression suite.
- **Acceptance:** All access paths enforce server-side tenant and role boundaries; privileged bypass is explicit/audited; constraints match approved domain behavior.
- **Rollback:** Revert application enforcement only if it causes a verified outage and after security owner review. For new constraints, follow an approved forward-repair plan; do not drop data or constraints without owner approval.

### Phase 6 — Redis/Celery, Docker, static/media, and edge

- **Objectives:** Provide production-shaped containers for one web runtime, PostgreSQL, Redis, and Celery; add Nginx only if the host needs it; prepare static/media and health behavior.
- **Files affected:** `kuzenga/Dockerfile` (adapted from `backend/Dockerfile`), `kuzenga/docker-compose.yml`, `requirements/*.txt`, settings, `static/` asset build inputs, optional `deploy/nginx/`, task package only for approved jobs.
- **Dependencies:** Phases 2–5; selected hosting/network/secret/storage owners; no infrastructure secrets in Compose files.
- **Risks:** Container startup/migration races, Redis outage/retry storms, ephemeral uploaded media, forwarded-header trust, asset path changes.
- **Required tests:** Docker build; non-root runtime; container health/readiness; Postgres/Redis readiness; graceful Celery shutdown/retry; static collection; upload storage isolation; reverse proxy security headers and max body size.
- **Acceptance:** Local Compose reproducibly starts a single canonical app; production image runs production settings; service dependencies and state persistence are explicit; tasks are idempotent.
- **Rollback:** Deploy previous immutable image and config; keep DB schema backward compatible. Disable new worker/task routes if needed; restore persistent data from verified backup only under approved recovery process.

### Phase 7 — CI and release controls

- **Objectives:** Automate quality/security checks and image build using GitHub Actions, with protected manual production deployment approval as a later separately approved workflow.
- **Files affected:** `.github/workflows/ci.yml` (new), dependency lock/constraints if selected, test config, documentation/runbooks.
- **Dependencies:** Stable test commands, PostgreSQL CI service, action/version review, repository permissions/secrets policy.
- **Risks:** Exposed secrets to untrusted PRs, flaky DB tests, unpinned actions, accidental deploy from pull requests.
- **Required tests:** Workflow run on branch/PR; verify tests/lint/migration checks/dependency scan/build; assert no deployment job or secret is available to untrusted PR context.
- **Acceptance:** Required checks are reproducible and branch protections are set by repository owner; deployment requires explicit protected environment approval.
- **Rollback:** Disable or revert workflow file; retain last known-good artifact and manual tested procedures. Do not automatically roll back schema changes.

### Phase 8 — Cutover and deprecate standalone foundation

- **Objectives:** Route all development/deployment through `kuzenga/`; stop separate `backend/` runtime and prevent new code from landing there.
- **Files affected:** `backend/README.md`, `ARCHITECTURE.md`, project manifests/settings/runtime files, repository documentation, ownership/CI paths. File deletion or archival is a separate owner-approved action.
- **Dependencies:** Prior phases accepted; owner confirms canonical ADR status and cutover criteria; application/database restore verified.
- **Risks:** Missed consumers, stale deployment secrets, untracked scripts or developer workflows still targeting `backend/`.
- **Required tests:** End-to-end browser flows, API flows, auth/tenant regressions, production smoke/health, DB backup/restore, CI against only canonical project.
- **Acceptance:** One deployable Django app and one schema owner; old project receives no traffic or writes; all routes and operational jobs have named owners.
- **Rollback:** Re-point deployment to previous known-good canonical release. Do not reactivate both projects as concurrent writers; restore or replay data only with owner approval.

## 4. Cross-phase acceptance gates

- No school can access another school's records through template, API, admin, bulk, export, or Celery paths.
- Existing login, tenant switch, academics, student, guardian/enrolment, attendance, and entitlement workflows remain behaviorally compatible unless separately approved.
- The same Django user model and migration history remain authoritative.
- PostgreSQL tests pass before PostgreSQL is used for production data; SQLite-only success is insufficient.
- Deployment has working readiness/liveness, structured logs, secrets injection, static/media strategy, backup and tested restoration, and human-approved release process.
- The architecture owner changes ADR-0001 from PROPOSED only after explicit approval. The ADR does not itself authorize production cutover or destructive data operations.

## 5. Owner decisions before implementation

1. Approve `kuzenga/` as canonical or select another option.
2. Confirm production data source/DB, hosting, network ingress, static/media storage, backup objectives, and migration authority.
3. Approve API client types/authentication/CSRF/CORS/versioning and module API scopes.
4. Approve tenant/admin security policy and any model invariants that require database migrations.
5. Approve Redis/Celery operational responsibilities and the first justified asynchronous job before enabling tasks.
6. Approve CI required checks, dependency locking approach, and production environment deployment approvals.
