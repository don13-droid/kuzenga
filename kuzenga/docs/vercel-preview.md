# Kuzenga Preview deployment

This runbook accompanies the [proposed Preview decision](../../docs/architecture/decisions/0002-vercel-preview.md). Use the existing Django project in `kuzenga/`. The application continues to serve templates, HTMX, Tailwind, protected media and health routes through Django. Vercel detects the WSGI entry point and collects static files for its CDN. Local Docker and SQLite development keep their existing settings. WhiteNoise is unnecessary for native Vercel static delivery.

## 1. Confirm Vercel settings

In [Kuzenga project settings](https://vercel.com/donewells-projects/kuzenga/settings), verify the repository `don13-droid/kuzenga`, set Root Directory to `kuzenga`, use the detected Django framework and leave dashboard build overrides empty. Under Settings → Environments → Production → Branch Tracking, verify the production branch and turn off **Auto-assign Custom Production Domains** before any release. Keep Vercel Authentication enabled for Preview. Use the generated Vercel URL for the first rehearsal.

## 2. Prepare isolated Preview resources

- In Neon, create a dedicated Preview branch from a clean schema or use a separate project. Use synthetic fixtures. Avoid branching from data containing school records. Create Preview-only credentials and confirm the Preview endpoint and database against the Neon Console before using either URL. Use a runtime role with the required application privileges and a migration role with DDL privileges. For separate roles, ensure the migration owner grants the required access to tables, sequences and future objects.
- In Cloudflare R2, create a private bucket such as `kuzenga-preview`. Disable r2.dev and public custom domains. Create a bucket-scoped Object Read & Write token. The app serves images and documents through existing record authorization, with private no-store headers. Use synthetic uploads only and verify rejected cross-tenant requests.
- Keep production Neon and R2 credentials separate. In Cloudflare DNS, use Vercel's supplied records in **DNS only** mode if a custom domain is approved later. Vercel serves public static assets from its CDN. Keep authenticated HTML, HTMX responses and private media out of shared cache. R2 and DNS changes are independent.

## 3. Enter Preview settings in Vercel

Use Settings → Environment Variables and scope the values to **Preview**, preferably to the deployment branch during the first test. Enter secrets directly in the dashboard.

| Variable | Value |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.vercel` |
| `DJANGO_SECRET_KEY` | Unique long random Preview secret |
| `DJANGO_ALLOWED_HOSTS` | Exact Preview branch alias and any approved Preview host, comma-separated |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Optional comma-separated HTTPS origins for intentionally cross-origin POSTs. Same-origin forms require no entry. |
| `VERCEL_ENV`, `VERCEL_URL` | Enable Vercel system variables. Preview requires `VERCEL_ENV=preview`. |
| `KUZENGA_RESOURCE_ENV` | `preview` |
| `DATABASE_URL` | Preview Neon pooled URL with `sslmode=require`; retain Neon-provided channel binding if present |
| `KUZENGA_POOLED_DATABASE_HOST` | Exact Preview pooled hostname copied independently from Neon |
| `KUZENGA_STORAGE_ENDPOINT` | R2 S3 HTTPS endpoint from the Cloudflare dashboard |
| `KUZENGA_STORAGE_BUCKET` | Private bucket with a `-preview` suffix |
| `KUZENGA_STORAGE_ACCESS_KEY_ID`, `KUZENGA_STORAGE_SECRET_ACCESS_KEY` | Preview bucket-scoped key pair |
| `KUZENGA_STORAGE_REGION` | Optional, defaults to `auto` for R2 |

The runtime closes database connections per request, disables server-side cursors and psycopg automatic preparation for transaction pooling, and requires TLS. Hosted settings reject an environment mismatch, a mismatched pooled host, and an incorrectly scoped bucket name. Resource ownership must also be verified at the provider.

## 4. Plan and apply Preview migrations

In an operator shell or protected job, load `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `KUZENGA_RESOURCE_ENV=preview`, the direct Neon URL as `DATABASE_URL_UNPOOLED` with `sslmode=require`, and the exact independently verified direct endpoint as `KUZENGA_PREVIEW_DIRECT_HOST`. Keep the direct migration credential in this environment only.

From `kuzenga/` with Python 3.12 and `requirements.txt` installed, run:

```bash
python scripts/preview_migrations.py
python scripts/preview_migrations.py --apply
```

Review the plan before the second command. The script checks the migration graph and verifies direct and pooled hostnames and database names match the designated Preview resource. Vercel build and runtime do not run migrations.

## 5. Build, test and release

1. Review GitHub CI and the Vercel build for the exact commit. Git integration builds branches once the root and Preview variables are configured. Redeploy the reviewed Preview commit if an earlier build ran before configuration.
2. Verify HTTPS, Preview authentication, `/api/health/` 200 with a working database, the login forms, tenant isolation, and Tailwind and HTMX workflows. Inspect response headers for static cacheability and private media no-store.
3. Upload a synthetic image and document. Verify the files persist across deployments, another tenant cannot retrieve them, and anonymous R2 requests are denied. Use fixtures comfortably below 4.5 MB, allowing for multipart overhead. Vercel caps function request and response bodies at 4.5 MB, while current Django validation allows 5 MiB images and 10 MiB documents. Full-size upload/download support needs an authorized direct transfer design before production.
4. Add a protected health monitor, review request error rates, and record the tested commit, build ID and database migration state. Rehearse restoring a backup to an isolated branch and validate school and migration data.
5. For production, obtain separate approval for credentials, backup, migration and deploy. Smoke-test the staged production build using production settings and promote the verified immutable build manually. Record the previously healthy deployment. If release checks fail, roll traffic back to that build with operator approval. Database changes require a separate recovery decision. Use backward-compatible migrations or a reviewed forward fix.
