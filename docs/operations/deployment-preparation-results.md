# Deployment preparation results — 2026-11-10

Work is on `chore/vercel-deployment-preparation`. Owner approval is limited to
preparatory implementation under ADR-0002. No deployment, DNS change, paid
resource, production database modification, merge, push or commit was performed.
No live URL has been created or verified.

## Local tools

Vercel 65.14.0 and Neon CLI 9.3.2 were resolved from npm and installed into ignored
`.deployment-tools/node` with lifecycle scripts disabled. Node 26.13.0 satisfies
their published engine requirements. Both version commands succeeded, reporting
65.14.0 and 9.3.2 respectively.
No login, project link, secret upload or cloud operation was performed. GitHub CLI
remains unavailable; authenticated GitHub checks and protections still need review.
The initial registry connection failures recovered; this local tools installation
does not change application dependencies or install global CLI tools.

## Implemented changes

| Files | Change |
| --- | --- |
| `kuzenga/vercel.json`, `kuzenga/pyproject.toml`, `kuzenga/.python-version`, `kuzenga/manage.py` | Native Django configuration, explicit existing WSGI entrypoint, Python 3.12, production discovery default on Vercel, bundle exclusions and automatic Git deployment disabled. Local management commands retain the development default. Select project root `kuzenga` when eventually linking. |
| `kuzenga/requirements.txt` | Native dependency-discovery include of the existing production manifest. |
| `kuzenga/config/settings/base.py` | Do not read local dotenv in Vercel. Other application additions in this shared file belong to concurrent work. |
| `kuzenga/config/settings/production.py` | Strong signing-key validation, exact hosts and HTTPS CSRF origins, mandatory database TLS, short-lived Neon-compatible connections, disabled server-side cursors, database sessions, secure cookies and configurable HSTS scope. Require external storage on Vercel. |
| `kuzenga/apps/core/storage.py` | S3 image storage retains authorized Django `/media/` URLs instead of exposing bucket URLs. |
| `kuzenga/apps/students/storage.py` | Private document storage delegates to a configurable external alias; local behavior, historical migration import and no-public-URL contract retained. |
| `kuzenga/requirements/base.txt`, `kuzenga/requirements/constraints.txt` | Bounded django-storages S3 integration and exact resolved SDK/transitive versions. |
| `.gitignore`, `kuzenga/.gitignore`, `kuzenga/.vercelignore`, `kuzenga/.dockerignore` | Protect local credentials, tools, account metadata, databases and private uploads from source/upload/build contexts. |
| `kuzenga/.env.production.example` | Fake configuration examples only, excluded from deployment uploads. |
| `kuzenga/scripts/check_deployment.py` | Offline production security and temporary static collection checks, with byte-for-byte preservation of project assets. |
| `kuzenga/scripts/migrate_preview.py` | Plan-first preview migration rehearsal with explicit environment and exact direct database target checks. No production mode. |
| `kuzenga/tests/test_deployment.py` | Production rejection tests, storage/no-public-URL checks, missing S3 object behavior, cross-tenant document denial and migration-target safeguards. |
| `.github/workflows/ci.yml` | Preserve existing checks and disposable PostgreSQL migrations; add offline production/static verification and dependency cache inputs. No deployment workflow or secrets. |
| `docs/architecture/decisions/0002-vercel-deployment.md` | Record explicit owner approval for preparation only. ADR-0001 is not promoted to Accepted. |
| `docs/operations/vercel-deployment.md`, `kuzenga/docs/deployment.md`, `kuzenga/README.md`, `kuzenga/docs/student-management.md`, this report | Audit, environment contract, operations, approval boundaries, remaining blockers and evidence. |

No existing migration file, domain business service, authentication implementation,
tenant authorization, template or frontend asset was changed by deployment work.
Existing dirty frontend/attendance work was preserved. Assessments application,
routes, navigation, permissions, migrations and tests appeared concurrently and
were left intact; they are not deployment changes. Include all required reviewed
application files in any future release and rerun CI on that exact commit.

## Validation evidence

Local runtime: Windows, Python 3.15.2, Django 5.2.19, SQLite isolated test database.
Deployment/CI target: Python 3.12, PostgreSQL 16. Local results do not prove target
runtime or PostgreSQL compatibility.

Commands run from `kuzenga/`, using `DJANGO_SETTINGS_MODULE=config.settings.test`
for normal checks. Downloaded SDK dependencies were installed under ignored
`.deployment-tools/python` and supplied through `PYTHONPATH`; no global Python
package installation was performed.

| Command | Result |
| --- | --- |
| `python -m pip check` | Passed with isolated SDK dependency path. |
| `vercel.cmd --version`, `neonctl.cmd --version` from `.deployment-tools/node/node_modules/.bin` | Passed: 65.14.0 and 9.3.2; no authentication or cloud action. |
| `python -m ruff check .` | Passed before concurrent finance work arrived. Latest broad run reports two E741 errors in concurrent `apps/finance/services.py` (lines 126–127); left untouched. Deployment-owned files pass targeted lint. |
| `python manage.py check` | Passed, no issues. |
| `python manage.py makemigrations --check --dry-run` | Passed, no changes detected. No deployment migration generated. |
| `python scripts/check_deployment.py` | Passed strict deployment checks and static collection; no database or object provider contacted. Synthetic domain explicitly opts into strict HSTS. |
| `python -m pytest -ra -p no:cacheprovider --tb=short --maxfail=5 --basetemp WORKSPACE_UNIQUE_TEMP` | Final full run: **288 passed**, 16 existing Django URLField deprecation warnings, 146.88 seconds. Includes all 25 deployment tests and 11 concurrent assessments tests. Earlier full run: 281 passed before the final seven deployment cases were added. |
| `python -m pytest tests/test_deployment.py -ra -p no:cacheprovider --tb=short --basetemp WORKSPACE_UNIQUE_TEMP` | Intermediate focused run: 23 passed, 2 warnings, 20.51 seconds. Two subsequent native settings-discovery cases passed in the final full suite. |
| `git diff --check` | Passed before final documentation review; only Git CRLF conversion notices. |

The migration guard cases reject missing/SQLite URLs, wrong host, wrong database
and a pooled/mismatched endpoint. Native-discovery cases verify production on
Vercel and the preserved local development default. No live connection is attempted.

Earlier attempts failed due to sandbox access to downloaded package directories
and permissions on pytest's shared default temporary directory. Approved read
access and a fresh workspace-only `--basetemp` resolved those failures. Concurrent
assessments files briefly caused an unresolved import and a Ruff issue; final
system checks, lint and full tests passed after those files were present. An early
offline security check also flagged deliberate HSTS opt-outs; the strict synthetic
check explicitly enables them, while real-domain defaults retain the documented
W005/W021 review requirement. No checks were silenced.

## Outstanding release blockers and verification

1. **Upload compatibility:** Vercel's documented 4.5 MB request-body limit conflicts
   with current 5 MB image and 10 MB PDF validation limits. Preserve the working
   product contract. A separately reviewed tenant-authorized direct-upload design
   or hosting decision is needed before a full-feature release. Object storage
   configuration does not remove ingress limits.
2. **PostgreSQL:** No selected disposable Neon database or working local Docker
   engine. Real TLS connectivity, pooled behavior, full migrations, existing manual
   SQL/data migration review and PostgreSQL tests remain unverified. The new script
   is plan-first but cannot independently prove that operator-selected credentials
   belong to a non-production environment.
3. **Storage:** Provider, region, private bucket permissions, encryption and
   separate preview/production credentials are not selected. Actual writes, reads,
   streamed downloads, missing-object handling and tenant boundaries need a live
   non-production bucket rehearsal. No local uploads have been transferred.
4. **Build/runtime:** No clean Python 3.12 build, native Vercel build/bundle or live
   endpoint validation. Python 3.15 is not the deployment target. CI has been
   prepared locally but not triggered remotely by this work.
5. **Accounts and source:** GitHub/Vercel/Neon identity, Vercel team/project,
   protections, approved cost/region and source commit still need selection/review.
   No remote `develop` branch was created. Automatic Git deployment is disabled in
   source; real project/environment protections must also be inspected.
6. **Operations:** Backups, retention/RPO/RTO, database-plus-object restore rehearsal,
   alerts, ownership and rollback acceptance are not configured or verified.
7. **Domain/security:** Exact Spaceship domain/subdomain and existing DNS are not
   provided. Preserve Zoho MX/SPF/DKIM/DMARC. HSTS domain scope, proxy headers,
   CSRF behavior and HTTPS require review on the selected protected preview.
8. **Browser checks:** Platform/school login, HTMX forms, cross-instance sessions,
   core workflows, cross-tenant access, uploads and live static/CDN responses need
   browser/live verification after preview approval.

## Next actions

1. Review this preparation and concurrent source changes; run the exact release
   commit through Python 3.12/PostgreSQL CI. Resolve concurrent finance lint errors
   before claiming the complete tree is CI-clean.
2. Complete supported browser/CLI authentication with the owner and choose the
   Vercel team/project, isolated Neon preview target and private object provider.
   Load secrets only through approved secure environment input.
3. Resolve the upload blocker; rehearse migrations, storage and isolated restores.
4. Obtain explicit protected Preview deployment approval. Link/configure Git only
   after environment isolation and release controls are ready. Do not enable
   automatic deployment as part of preparation.
5. Verify the real preview URL, logs, security and workflows. Obtain the exact
   domain and propose project-specific DNS changes separately for approval.
6. Request production/migration/DNS/merge approvals only for a concrete reviewed
   release with completed acceptance evidence.

## Rules and decisions consulted

Root `AGENTS.md`; `.codex/rules/README.md`; all global rules 00–10; module index;
tenant, authentication, student and admissions module rules; ADR-0001 and approved
preparation scope of ADR-0002; canonical architecture and consolidation plan;
existing CI, application README and student media specification. Historical rules
still describe some implemented modules/CI as proposed; no governance document
was silently promoted to full production approval. Canonical project selection
for deployment follows the approved ADR-0002 scope while ADR-0001 remains proposed.

Official platform references are linked in [implementation operations](../../kuzenga/docs/deployment.md).
