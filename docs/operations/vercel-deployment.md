# Vercel deployment audit and release runbook

Status: Phase 1 audited on 2026-11-10; owner subsequently approved ADR-0002 for preparatory implementation only. Configuration, storage adapters, migration rehearsal tooling and CI checks are now prepared; see [implementation operations](../../kuzenga/docs/deployment.md). The audit findings below describe the baseline unless identified as implemented. No deployment, remote environment change, production database operation or DNS change performed. No infrastructure is claimed provisioned.

For final changes, CLI installation status, 288-test validation results and remaining blockers, see the [preparation results](deployment-preparation-results.md).

## Authority and scope

Read root `AGENTS.md`, global rules 00–10, module index and tenant, authentication, student and admissions rules; ADR-0001, architecture/consolidation documentation, existing CI, application README and student media operations. See [ADR-0002](../architecture/decisions/0002-vercel-deployment.md) for the proposed deployment topology.

`kuzenga/manage.py` is the existing product entrypoint and current CI target. It contains the custom user, shared-schema tenancy, HTMX templates and Tailwind assets. `backend/manage.py` is an independent DRF foundation, not the product runtime. Preserve both and do not connect the foundation to product data. ADR-0001 remains Proposed; its recorded implementation authorization covers Phase 1 consolidation. Some rules/module specs still describe infrastructure/CI/admissions as proposed despite existing implementation; this audit preserves implementation and flags documentation drift without declaring additional approvals.

## Repository and tooling inventory

- Remote: `https://github.com/don13-droid/kuzenga.git`. Read-only `git ls-remote --heads origin` confirmed only `main`, at `eb0e4f768039c922ff30e186fa346065e946d758`. No remote `develop` exists at audit time.
- Dedicated local branch: `chore/vercel-deployment-preparation`. Started with substantial existing dirty frontend/attendance changes, including an untracked migration and tests. They are not deployment changes and were not overwritten, staged or committed. Release source must include owner-reviewed application changes and migrations before deployment.
- Git 2.56.0, Python 3.15.2, Node 26.13.0, npm 11.20.0 available. Only Python 3.15 was listed by `py --list`; CI/Docker target 3.12. Local tests do not prove runtime parity.
- `gh`, `vercel`, `neon` and `neonctl` not found on PATH. npm global executable directory contained Codex, not these CLIs. CLI account authentication could not be checked. Successful public GitHub read access does not establish authenticated push access.
- `npm.cmd view vercel version engines --json` and the equivalent `neonctl` query both failed with `ECONNRESET` even with approved external network access. No CLI was installed; supported version verification and installation remain blocked by registry connectivity.
- `npm.ps1` is blocked by the current PowerShell execution policy; `npm.cmd` works without changing policy.
- Docker client is installed; engine unavailable. Docker config access was denied in sandbox. No PostgreSQL client tools found on PATH and no non-production Neon database selected.
- No tracked `.env` or SQLite files found by the targeted `git ls-files` check. Local `.env` contents and local database contents were not printed or inspected. This is not a full historical secret scan.

## Architecture and pipeline

`kuzenga/requirements/{base,production,development,constraints}.txt` is the existing dependency mechanism, with bounded direct requirements and exact constraints. `pyproject.toml` currently contains pytest/Ruff configuration, not package dependencies or Python runtime selection. There is no root `kuzenga/requirements.txt` for native dependency discovery. Add a thin include of the existing production requirements after topology approval, preserving one dependency source.

`manage.py` defaults to development settings; WSGI/ASGI default to production. Set `DJANGO_SETTINGS_MODULE=config.settings.production` explicitly for Vercel builds and runtime. Both entrypoints are configured; pin `config.wsgi:application` through native Vercel project metadata to avoid accidental ASGI selection. Verify the supported Python runtime against the pinned dependency set before release.

CI `.github/workflows/ci.yml` runs on pushes and pull requests to `main`/`develop`, with read-only permissions, pinned checkout/setup actions, Python 3.12 and PostgreSQL 16. It runs dependency installation/check, Ruff, Django checks, migration drift check, migrations and pytest. Preserve it. Deployment branch pushes alone do not trigger that workflow; a PR targeting a configured branch does. Existing remote checks, branch protection and environment approvals have not been inspected through an authenticated account.

Tailwind 3.4.17 is built through the documented `npx` command and tracked CSS. No package manifest or esbuild pipeline was found in the inspected tracked application. Preserve current CSS, JavaScript and HTMX template design. HTMX is loaded from unpkg; README already flags vendoring it before production. Do not introduce a frontend framework or invent an esbuild requirement.

## Blocking and unresolved items

| Item | Evidence / required resolution |
| --- | --- |
| Topology governance | Architecture/CI rules require owner-approved deployment ADR before implementation; ADR-0002 is prepared for review. |
| Durable media | Default image storage is local. `StudentDocumentStorage` explicitly subclasses `FileSystemStorage` and is referenced by historical migrations; replacing only default storage is insufficient. |
| Private access | Existing `/media/` and document downloads authorize records and open their storage streams. Keep those routes; never expose a public bucket or bypass tenant checks with raw object URLs. |
| Upload limits | Existing documents allow 10 MB PDFs and images up to 5 MB. Validate actual platform ingress/response limits before claiming workflow compatibility; smaller serverless limits require a separately reviewed authorized upload design. |
| Database | Production already rejects SQLite; TLS/pooler configuration and cursor behavior are not enforced. No Neon connectivity or PostgreSQL migration rehearsal yet. |
| Host/origin security | Secure cookies, HTTPS redirect, proxy header, HSTS and explicit host checks exist. Trusted origins need environment configuration and HTTPS validation. Avoid broad wildcard preview hosts/origins. |
| Sessions | Django default database sessions are already durable when PostgreSQL is configured. No custom session/cache configuration found; do not introduce process-local sessions. |
| Source hygiene | Dirty application changes must be reviewed and included intentionally; never deploy this checkout through an indiscriminate CLI upload. Ignore local databases, media, secrets and developer artifacts in upload packaging. |
| Accounts and release | No selected Vercel team/project, Neon project/region, object-storage provider, domain, budgets or protected preview configuration. |
| Recovery | Backup retention, RPO/RTO, restore rehearsal and monitoring ownership unverified. |

## Phase 2: native Vercel preparation after ADR review

1. Use project root `kuzenga`, native Django framework and explicit WSGI entrypoint. Add only native configuration; no legacy `builds`/catch-all `/api` wrapper.
2. Add the dependency-discovery include, supported Python version and source exclusions. Ensure nested requirement includes and constraints install in a clean build.
3. Preserve console logging, secure cookies, CSRF middleware and HTTPS proxy handling. Configure exact hosts and HTTPS trusted origins per environment. Review HSTS subdomain/preload scope before enabling a domain shared with other services.
4. Keep `STATIC_ROOT`/`STATIC_URL`; native Vercel runs `collectstatic` and serves collected files through its CDN. Verify Tailwind, layout CSS, JavaScript and admin assets. Build CSS only if required; never run migrations as a build command.
5. Validate production settings using generated temporary test inputs, without live credentials. Confirm build does not open the database, write persistent runtime files or print settings/secrets.

## Phase 3: Neon and controlled migration procedure

- Provision/select separate non-production and production data environments only after account, region and cost approval. Preview must not inherit production `DATABASE_URL` or real school data. Prefer clean test fixtures; Neon branches copied from production also copy sensitive data.
- Runtime `DATABASE_URL`: Neon pooled hostname, TLS required, `CONN_MAX_AGE=0`, `DISABLE_SERVER_SIDE_CURSORS=True`; validate transport settings rather than silently accepting insecure URLs. Preserve Neon-supplied channel binding parameters where applicable.
- Migration operator: direct TLS connection and separate credentials, available only to the approved release session. Never put it in a request handler, startup hook or preview build. Never print the connection string or pass secrets as visible shell arguments.
- First rehearse against an explicitly selected disposable non-production database: `python manage.py check`, `python manage.py migrate --plan`, reviewed SQL for manual migrations, `python manage.py migrate --noinput`, migration drift check and full PostgreSQL tests. Tests need a role permitted to create an isolated test database, or a separately configured isolated test database.
- Manual SQL exists in `students.0002_student_management` and `academics.0004_curriculum_structure`; `core.0002` includes a data migration. SQLite success is insufficient evidence of PostgreSQL behavior and lock duration.
- Release one reviewed migration execution at a time, with recorded commit, target identity, backup verification, operator and stop-on-failure behavior. Apply backward-compatible changes before switching traffic. Production database operations require explicit approval.
- Back up database and private object storage independently. Owner must choose retention, encryption, access controls, offsite needs and recovery objectives. Verify Neon restore window for the selected plan; rehearse a restore into an isolated target, checking users, tenant ownership, row counts and file references. Use direct connections for logical backups; store archives encrypted outside Git/build output. Never restore over production as a test.

## Phase 4: media and background work

Configure a bounded `django-storages`/S3 SDK dependency only after provider selection. Use private buckets and environment-specific credentials/prefixes with least-privilege access. Preserve image URLs through the authenticated Django route. Adapt `StudentDocumentStorage` while keeping its import path and no-public-URL contract compatible with historical migrations; do not edit old migrations. Preserve existing upload names and database references. Existing file transfer, if needed, is a separately reviewed operation with checksums and no deletions.

Test authorized uploads/downloads, cross-tenant denial, missing objects, content validation and storage failures with a fake backend, then a dedicated non-production bucket. Confirm attachment/security headers. Never configure public object ACLs or CDN caching for private responses. Larger uploads may need tenant-authorized, short-lived object upload grants and post-upload validation; treat that as an interface change requiring review.

The inspected application has no implemented Celery/Redis task integration or persistent worker. Provisioning and migrations are management operations; future bulk imports, report exports, document scanning or email batches should run outside request deadlines through an approved queue/worker. Reuse domain services with explicit tenant/actor context, idempotency and bounded retries. Do not install a broker without an approved workload and owner.

## Phase 5: authentication and Git integration

Install pinned supported CLIs in an isolated tool location without modifying app dependencies. Verify versions/help before interactive use. GitHub CLI uses `gh auth login`; Vercel uses `vercel login`; Neon uses its supported browser authentication flow. User completes browser login; do not request passwords/tokens in chat or print credential stores.

Before linking, confirm the GitHub identity, Vercel team/project and Neon project. Linking Git can trigger deployments: do it only after preview approval and environment isolation. Configure `main` as production and `develop` as preview; creating/pushing `develop` is still pending. Explicitly disable or protect automatic production deployment until owner release approval. Preserve all GitHub checks and require their success; Vercel Git builds alone do not prove CI passed. Never force-push or reset history.

Use Vercel dashboard or interactive secure CLI input for secrets. Required environment categories: Django secret/settings/hosts/origins, pooled database URL, storage endpoint/region/bucket/access keys and log level. Different environment scopes must have independent values. Keep migration credentials out of the app runtime where possible. Do not pull environment files into tracked paths or commit `.vercel` metadata containing account/project details.

## Phase 6: Spaceship domain

Ask for the exact registered domain and desired application hostname. Read existing DNS records and obtain Vercel's project-specific required records before proposing a change. Preserve apex/other applications and every Zoho MX, SPF, DKIM and DMARC record. Never replace the zone or change nameservers as a shortcut.

Present exact owner-reviewed hostname/type/value/TTL changes using the values Vercel reports. Do not assume a generic CNAME or IP. Apply only after explicit DNS approval, or provide minimal manual steps if API access is unavailable. Verify authoritative/public resolution, Vercel domain ownership, certificate issuance and HTTPS before marking complete.

## Phase 7: validation evidence

Run from `kuzenga/` with `DJANGO_SETTINGS_MODULE=config.settings.test`:

| Command | Audit result |
| --- | --- |
| `python manage.py check` | Passed; no issues. |
| `python manage.py makemigrations --check --dry-run` | Passed; no changes detected. |
| `python -m pip check` | Passed; no broken requirements. |
| `python -m ruff check .` | Passed. |
| `python -m pytest -ra -p no:cacheprovider` | 252 passed, 16 Django URLField deprecation warnings, 85.27 seconds. SQLite test database, Python 3.15.2. Includes existing dirty attendance tests. |
| `git ls-remote --heads origin` | Passed with approved network access; remote `main` only. |
| `docker info --format '{{.ServerVersion}}'` | Failed: daemon unavailable; sandbox also denied Docker config access. No container tests performed. |

Not verified: clean Python 3.12 dependency installation, Vercel build, production `check --deploy`, PostgreSQL connectivity/migrations/tests, S3 operations, browser interactions, authenticated remote CI/protections, deployed endpoints/logs, DNS or certificates. No live URL exists from this work.

After preview authorization, deploy reviewed source only into protected preview using isolated data. Verify health, platform and school login, CSRF forms/HTMX, session persistence across instances, cross-school read/write/media denials, attendance/admissions/student workflows, static files and uploads/downloads. Inspect sanitized logs for errors. Run `check --deploy` with the actual selected production configuration without exposing it.

## Phase 8: production release gates

- [ ] ADR/topology reviewed; canonical project authority accurately recorded.
- [ ] Reviewed source and migrations on a dedicated PR; required CI checks pass under deployment Python/PostgreSQL versions.
- [ ] Selected accounts, region, cost limits and operational owners recorded.
- [ ] Preview/production database, bucket access and secrets separated; no real school data in preview.
- [ ] PostgreSQL migration rehearsal, private object storage and platform upload limits verified.
- [ ] Backup retention/RPO/RTO approved; isolated database and file restore rehearsed.
- [ ] Error monitoring, alert recipients, health checks, log privacy and rollback triggers verified.
- [ ] Git deployment controls prevent unapproved production releases.
- [ ] Protected preview explicitly authorized, deployed and tested; live URL and logs verified.
- [ ] DNS proposal reviewed; Zoho records preserved; DNS changes separately approved.
- [ ] Explicit production approval received for the exact reviewed release and database plan.
- [ ] HTTPS, live workflows and tenant isolation pass before real school access is enabled.

## Official references

- [Vercel native Django deployment](https://vercel.com/docs/frameworks/full-stack/django): native entrypoint discovery, WSGI selection, dependency/build setup and automatic static collection. Consulted 2026-11-10; page reports minimum CLI 50.38.0.
- [Neon Django integration](https://neon.com/docs/guides/django): TLS, cursor configuration and connection lifetime.
- [Django 5.2 database documentation](https://docs.djangoproject.com/en/5.2/ref/databases/): transaction-pooler and cursor compatibility.

Recheck platform limits, supported runtimes and CLI versions at implementation time.
