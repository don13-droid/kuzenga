# Deployment preparation: Vercel and Neon

Owner approved ADR-0002 for preparatory implementation only on 2026-11-10.
No deployment, DNS write, paid resource, production database operation or merge to
`main` is authorized. See the [approval record](../../docs/architecture/decisions/0002-vercel-deployment.md)
and [audit/release checklist](../../docs/operations/vercel-deployment.md).

## Runtime and assets

Select the existing repository with **Root Directory `kuzenga`**, native **Django**
framework and Python **3.12** (`.python-version`). `requirements.txt` includes the
existing production requirements/constraints; it is not a second dependency list.
`tool.vercel.entrypoint` pins `config.wsgi:application`. `vercel.json` sets production
entrypoint options, excludes local data from the function and disables **all automatic Git
deployments**. This is a source safeguard, not proof of remote account controls.
Do not link/import/deploy until a preview release is explicitly approved.
`manage.py` defaults to production on Vercel for both native build discovery and
management commands; local development keeps its existing default. Explicitly set
the production settings module in remote environment scopes too. No legacy
`env`/`build.env` property is used in `vercel.json`.

Native Vercel collects static files and serves `/static/` through its CDN. Existing
Tailwind CSS, layout CSS, JavaScript and Django admin assets are retained. No
template redesign, migration changes, frontend framework or legacy `/api` wrapper
is introduced. Rebuild Tailwind with the existing README command when templates
change. No migration is part of build or request startup.

`.vercelignore` and function exclusions protect dotenv files, SQLite databases,
private uploads, environments, IDE files and developer artifacts. Keep the root
directory selection exact; never upload the repository's dirty checkout blindly.
The existing Docker runtime is retained and is separate from native Vercel.

## Environment contract

Use the dashboard/interactive secure input. Do not paste credentials into chat,
CLI arguments, tracked files or logs. `.env.production.example` contains fake
documentation values and is excluded from deployment uploads. On Vercel,
`base.py` does not read `.env` at all.

| Variable | Requirement |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production`; explicitly set in the remote build/runtime environment scope. Native discovery also defaults to production when `VERCEL=1`. |
| `DJANGO_SECRET_KEY` | Independently generated per environment; at least 50 characters, not a placeholder or repeated character value. |
| `DJANGO_ALLOWED_HOSTS` | Exact comma-separated hostnames; no wildcard, leading dot, URL scheme or port. Include only the selected preview/custom domains. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Exact HTTPS origins matching allowed hosts; optional for same-origin requests. Do not trust every `vercel.app` deployment. |
| `DATABASE_URL` | Pooled Neon PostgreSQL URL with `sslmode=require` or stronger; retain Neon channel-binding parameters. Never reuse production credentials in preview. |
| `MEDIA_STORAGE_BACKEND` | `s3` on Vercel; missing/`filesystem` is rejected there. Non-Vercel production retains filesystem compatibility. |
| `S3_ENDPOINT_URL` | HTTPS URL for a selected S3-compatible provider; omit for AWS S3. |
| `S3_REGION_NAME`, `S3_BUCKET_NAME` | Explicit selected region/private bucket. Production and preview require separate storage permissions. |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Scoped credentials; no public object ACLs or public bucket policy. |
| `S3_ADDRESSING_STYLE` | `auto` by default; use a provider-supported choice after integration testing. |
| `LOG_LEVEL` | Console logging, default `INFO`; do not enable sensitive request/query logging. |
| `DJANGO_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_HSTS_PRELOAD` | Default false; enable only after reviewing every affected domain service. Django deployment checks warn W005/W021 when these are false; review the domain policy before release. |

Production enforces HTTPS redirection, secure cookies, HttpOnly session cookies,
same-site cookies and trusted proxy HTTPS indication. Sessions use Django's
database backend. Tenant middleware and authentication are unchanged. The ingress
must control `X-Forwarded-Proto`; verify this on the eventual preview.

Database connections use `CONN_MAX_AGE=0`, health checks, disabled server-side
cursors and a connection timeout. Insecure `sslmode` values are rejected; absent
mode defaults to `require`. No client process pool or in-memory session store is
introduced. Local development/test SQLite behavior remains available.

## Private external media

`django-storages[s3]` and its boto SDK dependencies are constrained in the existing
requirements files. They are used only when `MEDIA_STORAGE_BACKEND=s3`; provider
selection and bucket creation are outstanding. django-storages is BSD licensed;
boto3/botocore use Apache-2.0. Review dependency updates and platform bundle size
as part of release maintenance.

`ProtectedImageStorage.url()` preserves `/media/<name>`; browser requests still
pass through the existing record/tenant authorization before storage is opened.
`StudentDocumentStorage` retains its historical import/deconstruction path and
no-public-URL contract. It delegates to a private storage alias when configured,
or the existing private filesystem root in local development. Existing document
and admissions download routes continue to authorize access and stream the file.
Existing migration files and uploaded key names are untouched. S3 writes disable
overwriting and request private/no-store cache metadata; the operator must also
verify bucket policy, public-access blocking and encryption for the selected
provider. No existing local uploads have been transferred.

**Release blocker:** Vercel documents a **4.5 MB request body limit**, including
multipart overhead. Current forms permit 5 MB images and 10 MB PDFs. External
storage alone does not fix this ingress limit. Preserve current validation and
require a separately reviewed tenant-authorized direct-upload workflow or another
hosting decision before claiming full upload compatibility. Existing streamed
downloads require platform validation too. Do not silently lower product limits.

## Offline preparation checks

Install `requirements/development.txt`, then run from this directory:

```powershell
$env:DJANGO_SETTINGS_MODULE = 'config.settings.test'
python -m pip check
python -m ruff check .
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -ra
python scripts/check_deployment.py
```

`check_deployment.py` launches production settings with synthetic database/storage
credentials and a generated temporary signing key; it never contacts a database
or bucket. It runs strict Django deployment checks against a synthetic domain with
strict HSTS enabled, collects static files into a temporary directory and verifies
every existing project static asset is preserved byte-for-byte. This does not
prove that the eventual real environment is secure or reachable. Run real
`check --deploy` and assess warnings after domain/environment selection.

CI preserves all existing PostgreSQL 16/Python 3.12 checks and adds this offline
production/static check. It includes no deployment job, account secret or Vercel
login. CI migration execution remains limited to its disposable PostgreSQL service.

## Explicit non-production migration rehearsal

First obtain owner confirmation of an isolated preview database and securely load
`DIRECT_DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` and any required
storage environment. Use the direct Neon endpoint, not the `-pooler` hostname.
Do not place migration credentials in Vercel's runtime environment.

```powershell
$env:DEPLOYMENT_ENVIRONMENT = 'preview'
python scripts/migrate_preview.py --expected-host DIRECT_HOST --expected-database PREVIEW_DATABASE
# Review the plan, target ownership, SQL, compatibility and backup evidence first.
python scripts/migrate_preview.py --expected-host DIRECT_HOST --expected-database PREVIEW_DATABASE --apply
```

The tool checks the preview declaration, exact host/database and direct PostgreSQL
URL, then invokes the existing migration engine. Default behavior is plan-only.
It does not create resources, infer environment ownership or prove a database is
non-production; expected-target verification is the operator's responsibility.
Run one operator at a time. There is no production mode. Production migration
approval must be obtained separately, with verified backups and an approved
release procedure. Do not add migrations to a Vercel build or request.

After applying on the selected disposable database, run the complete PostgreSQL
test suite with isolated test database permissions. Review existing manual SQL/data
migrations. Back up PostgreSQL and objects separately; choose recovery objectives,
retention and an operational owner, then rehearse restore into isolated targets.

## Remaining deployment steps

1. Review concurrent application changes and all migration files; run CI against
   the exact reviewed commit under Python 3.12 and PostgreSQL 16.
2. Select Vercel team/project, Neon preview/project/region and private object
   provider/bucket. Complete supported CLI/browser authentication with the owner.
3. Resolve the upload limit blocker; test actual provider storage, data separation,
   migration compatibility, backup restore and monitoring.
4. Obtain explicit protected Preview deployment approval. Configure project root,
   exact preview hosts/origins and secrets before linking Git. Keep all automatic
   deployment disabled until separately approved; map `main` to production and
   `develop` to preview when release controls are ready.
5. Verify the live preview URL, logs, login portals, HTMX/CSRF, session persistence,
   cross-tenant authorization, private media, static assets and core workflows.
6. Obtain exact Spaceship domain/subdomain and inspect Vercel-required DNS records.
   Propose minimal changes preserving all Zoho mail records; apply only after DNS
   approval. Production deployment and merging require separate explicit approval.

## Official references

- [Native Django on Vercel](https://vercel.com/docs/frameworks/full-stack/django)
- [Python runtime and version selection](https://vercel.com/docs/functions/runtimes/python)
- [Disable automatic Git deployment](https://vercel.com/docs/project-configuration/git-configuration)
- [Vercel payload limits](https://vercel.com/docs/functions/limitations)
- [Neon Django configuration](https://neon.com/docs/guides/django)
- [django-storages S3 options](https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html)
