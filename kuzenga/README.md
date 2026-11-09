# Kuzenga - School Management Platform

Modular monolith (Django + HTMX + Tailwind), multi-tenant (shared schema), with subscription entitlements.
Built from `Kuzenga_School_Management_System_Product_and_Technical_Blueprint.docx`.

## Quick start

1. Create a Python 3.12+ virtual environment and activate it.
2. Install the pinned development dependency set and create your local environment file:
   ```
   python -m pip install -r requirements/development.txt
   copy .env.example .env          (Windows)   |   cp .env.example .env   (macOS/Linux)
   ```
3. Apply the existing migrations, create the catalogue/demo tenant if desired, then start Django:
   ```
   python manage.py migrate
   python manage.py seed_catalog
   python manage.py provision_tenant --name "Demo High School" --slug demo --owner-email you@example.com --password "ChangeMe123!" --plan standard
   python manage.py createsuperuser        # platform admin, for /admin/
   python manage.py runserver
   ```
4. Open http://127.0.0.1:8000/ and sign in with the owner account. The default local database remains `db.sqlite3` for compatibility with existing local development.
5. Run checks: `python -m pytest`, `python manage.py check`, `python manage.py makemigrations --check --dry-run`, and `python -m ruff check .`.

`requirements/constraints.txt` pins the resolved direct and transitive package versions. Update it deliberately when dependencies change, then verify installation and tests in the documented Python/Docker versions.

## Continuous integration

GitHub Actions runs Ruff, Django system and migration checks, migrations, and the pytest suite on pushes and pull requests targeting `main` or `develop`. The workflow uses Python 3.12 and a temporary PostgreSQL 16 service. Test settings use `DATABASE_URL` when supplied; without it, local tests continue to use an in-memory SQLite database. To enable CI, push this repository to GitHub with the workflow file at `.github/workflows/ci.yml`; GitHub runs it automatically for those branches and their pull requests. The workflow needs no repository secrets or write permissions.

## Frontend assets

The Django templates load Tailwind from `static/css/tailwind.css`. Rebuild it after changing Tailwind classes in templates or rendered Python strings:

```powershell
npx --yes tailwindcss@3.4.17 --input tailwind.input.css --output static/css/tailwind.css
```

Tailwind scans templates and Python-rendered class strings according to `tailwind.config.js`.

## Docker development environment

Copy `.env.example` to `.env`, replace the local placeholder secret/password, then run from this directory. If reusing a PostgreSQL volume created by the previous Compose file, set `POSTGRES_USER`, `POSTGRES_DB`, and `POSTGRES_PASSWORD` to the credentials/database used when that volume was initialized; Compose keeps the existing `pgdata` volume name:

```powershell
docker compose up --build
```

Compose starts PostgreSQL and the Django development server, waits for PostgreSQL health, and applies the existing migrations. Check `http://localhost:8000/health/` or `http://localhost:8000/api/health/`. Compose constructs a PostgreSQL URL from `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`; use a URL-safe local password. This Compose setup is for local development and is not the production deployment configuration.

## Configuration

The authoritative Django project and settings are under this `kuzenga/` directory. `backend/` at the repository root is retained as a temporary infrastructure reference and must not receive product features or be run as a competing backend.

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django signing key; use a generated secret outside local development. Production rejects the local placeholder. |
| `DJANGO_DEBUG` | Development debug flag. Production settings always disable debug. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames. Development has localhost defaults; production requires a value. |
| `DATABASE_URL` | Django-environ database URL. Local Python defaults to SQLite to preserve existing local setup; production requires PostgreSQL. |
| `DB_CONN_MAX_AGE` | Persistent database connection lifetime in seconds (default 60). |
| `LOG_LEVEL` | Console logging threshold (default `INFO`). |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Local Compose database values. The password is a development placeholder and must not be reused in production. |

For direct PostgreSQL development, set `DATABASE_URL` to a PostgreSQL URL reachable from the host. For production, select `DJANGO_SETTINGS_MODULE=config.settings.production`, provide a PostgreSQL `DATABASE_URL`, non-placeholder secret, explicit allowed hosts, and trusted HTTPS proxy configuration. Keep `.env` out of version control.

## Platform tenant directory

The application root (`/`) sends signed-out users to the school login, sends platform superusers to the tenant directory, and opens the school dashboard for authenticated users with an active tenant. School users sign in at `/login/`; platform superusers use the separate `/platform/login/` portal. Each portal rejects the other account type. Platform pages and sign-out use their platform-specific routes. Users without an active tenant are sent to tenant selection. Platform superusers can open the tenant directory at `/platform/tenants/`. It shows database-backed tenant and subscription metrics, supports search/filter/sort/pagination, provides an HTMX quick-view drawer, and exports the active filters as CSV. The directory reuses the existing `Tenant`, `Membership`, `User`, `Plan`, and `Subscription` records and is guarded by `is_superuser` checks on each page and export request. The current schema stores a tenant country code but no street address or school contact fields; those details are shown as unavailable when no administrator membership provides an email.

Platform superusers can start tenant registration from the directory using **Register Tenant** at `/platform/tenants/register/`. The four-step wizard persists non-password progress in the server session and creates the tenant, initial owner, selected plan, and initial academic year in one transaction. The administrator sets the initial password on the final step; Django validates and hashes it, and the wizard does not put it in the session. There is no invitation email service, so the platform operator must deliver that initial password through a separate secure channel. Current models do not store a school registration number/type/address/contact details or an administrator phone/username; the wizard does not collect unsupported fields. New registrations use the existing plan activation and entitlement service, with suspended and archived states immediately suspending access; this does not add billing behavior.

Each Tenant Directory school name and **View Details** link opens its Tenant Overview at `/platform/tenants/<tenant_uuid>/`. The overview reads the existing tenant, membership, subscription, audit-event, student, and class records. **Configure Tenant** opens the tenant-scoped configuration workspace at `/platform/tenants/<tenant_uuid>/configure/`; **Manage Users & Staff** opens Tenant Administration at `/platform/tenants/<tenant_uuid>/users/`. Tenant Administration reuses the global `User`, tenant-scoped `Membership`, and established `Role` records. Platform superusers manage a selected tenant; school owners and administrators can manage only their active school membership from `/school/users/`. User creation creates an invited membership and a secure activation link; no email is sent because delivery is not configured. Activation and password setup use Django's token and password-validation mechanisms. School deactivation suspends only that tenant membership, preserving the shared identity and historical records. School administrators cannot change shared global profile details or reset an identity shared with another school. The primary owner cannot be reassigned or deactivated through this module. The read-only roles page documents the existing permission registry; administrators receive `users.view` and `users.manage`, enforced in views as well as the navigation. **Edit Tenant** and subscription administration remain in Django admin. The configuration workspace manages academic years, terms, calendar events, education levels, classes, departments, subjects, assessment categories, grading boundaries, attendance statuses, school identity/contact details, regional settings, and notification preferences using existing tenant-owned models. Attendance status choices are applied to the school's register and validated server-side. Notification preferences are stored for use by communication features; no delivery provider is configured. The overview's CSRF-protected suspend/reactivate action records the prior active or trial state and restores it on reactivation; archived tenants cannot be changed through this action. Platform superusers can also edit tenant details in Django admin; the edit form includes **School Information and Contact Details** plus **Primary Administrator Details** for the active owner or administrator membership. School and administrator phones are stored separately. School logos and administrator profile images accept validated JPEG, PNG, or WebP files up to 5 MB, stored through Django's configured media storage; existing files can be replaced or removed. Apply the `accounts.0002` and `tenancy.0002` migrations to add the optional fields.

## Module 05: Tenant Subscription Management

From a Tenant Overview, **Manage Subscription** opens `/platform/tenants/<tenant_uuid>/subscriptions/`. Platform superusers can add a manual subscription or edit an existing record's plan, status, start, expiry and trial expiry. Each write requires a reason. Subscriptions and their event history are paginated; the workspace also lists currently valid module grants. School accounts cannot access these routes. Subscription records in Django admin are now read-only; use the platform workspace to keep grants synchronized.

The workspace reuses the existing tenancy models and catalogue. Saving an active or trial subscription replaces only that subscription's plan/trial grants using its recorded start and expiry. Trial grants end at the trial expiry. Other statuses grant no access through this workflow; no grace-period access policy is assumed. Changing one subscription preserves other subscriptions and independent add-on, promotion or exception grants. Multiple subscriptions may coexist as before; use **Edit** to change an existing plan rather than adding another record when replacing it. Tenant status and membership permissions continue to control school access independently.

Changes and reasons are recorded atomically in `SubscriptionEvent` and `core.AuditEvent`, including before/after field values in the audit event. Unchanged edits produce no additional history. Subscription history rejects ordinary instance/queryset updates and deletes; this is application-level protection, not database-level tamper-proofing. Cross-tenant subscription links on entitlement and history saves are rejected. Start/expiry ordering, trial boundaries, active plans and plan module dependencies are validated. The initial plan activation service now respects future start dates.

Apply `tenancy.0004_subscription_tenant_index` after the existing migrations. It only adds a tenant/creation-time index; no data is rewritten or removed. Existing records are not retroactively repaired. The migration is reversible by removing the index. The test suite applies the migration to its temporary SQLite database; production PostgreSQL execution still needs verification.

Billing providers, prices, invoices, automatic renewals, proration, automatic status transitions and grace-period policy remain pending specification. This implementation provides manual administration of the established subscription and entitlement concepts without choosing those policies.

## Tenant activity and audit logs

Platform superusers can review the chronological event feed at `/platform/activity/`, open a tenant history at `/platform/activity/tenants/<tenant_uuid>/`, and inspect a user's activity at `/platform/activity/users/<user_uuid>/`. Event details are available at `/platform/activity/events/<event_uuid>/`. Search, category, action, outcome, tenant, date-range filters and 50-row pagination operate on stored audit events. School accounts do not have audit-log access because no school-level audit-view permission has been specified.

The existing `core.AuditEvent` model is the audit source of truth. It records tenant registration/profile/status changes, tenant configuration, user and membership changes, authentication outcomes, subscription and entitlement changes, and selected student/attendance events. Request metadata stores the direct remote IP, bounded user-agent, HTTP method and resolved route name; it does not store URL paths, session IDs, credentials or auth tokens. Sensitive field names in metadata and before/after changes are redacted. Authentication failure records do not persist the submitted password or raw unknown username.

Audit event updates and deletes are rejected by the model, ORM manager, and Django admin interface; referenced users and tenants are protected from ordinary deletion to retain attribution. This is application-level append-only behavior, not database-level tamper-proofing. No audit retention or purge policy has been configured.

## What exists

Module 07 adds school-level [admissions and enrolment](docs/admissions.md) at
`/admissions/`, including intake, review decisions, private supporting documents
and transactional conversion into the existing Student Management records.
School owners/administrators can access it from the school sidebar; platform
superusers are explicitly excluded from this workflow.

Module 06 extends the existing student workflows with editing, filters, guardian
reuse/emergency contacts, status changes, profile photographs, private documents
and audit history. Shared media delivery and layout fixes are included. See
[student management and media operations](docs/student-management.md) for routes,
permissions, storage/deployment requirements, migration notes and browser checks.

| App | Purpose |
| --- | --- |
| `core` | Tenant context, `TenantScopedModel` (auto-scoped, fail-closed), audit log, tenant-safe forms |
| `accounts` | Custom email-login `User` (global identity) |
| `tenancy` | Tenant, Membership + roles, permission registry, Module/Plan/Subscription/Entitlement, middleware, access decorators |
| `academics` | Years, terms, grades, classes, subjects |
| `students` | Students, guardians, enrolment history, admission numbers |
| `attendance` | Daily class register (open -> submit) |

## Rules to keep (from the blueprint)

- Every tenant-owned model extends `TenantScopedModel`. Use `Model.objects` in school code, never `Model.unscoped`.
- Every view uses `@access_required(module=..., permission=...)` (or `TenantAccessMixin`).
- Business rules live in `services.py`, not views or templates.
- New module = entitlement code in `seed_catalog` + nav entry in `tenancy/navigation.py` + permissions in `tenancy/permissions.py`.
- Add a tenant-isolation test for every new feature (see `tests/test_tenant_isolation.py`).

## Current operational limits

The project now has a canonical Dockerfile, local Compose services, environment-based settings, PostgreSQL configuration, DRF infrastructure, logging, and DB-aware health routes. PostgreSQL and Docker execution still require verification in an environment with those services available.

Before production, vendor HTMX (still loaded from a CDN), configure a production static-file server/edge and persistent private media storage for uploads, verify PostgreSQL migrations and restore procedures, define Redis/Celery operations for an approved asynchronous workload, establish CI/CD and deployment approvals, and inject real secrets. The Tailwind stylesheet is compiled locally with the documented command. The production Docker image uses Gunicorn; local Compose uses Django's development server.
