# Local/GitHub integration - 15 November 2026

Status: source integration for draft review only. No main merge, deployment, DNS,
production environment update or production database operation is authorized or performed.

## Recovery and starting state

Main and origin/main both pointed to `9b54cff4fa8ef34ba51852530ccb1a0409ca45ec`.
The main worktree had only the untracked nested `.worktrees/` directory. Its
`public-ui-recovery` worktree was on `feat/public-ui-migration-recovery` at
`d6f311f`, with four modified files (corporate CSS/JS, public template, public
website tests), a new visual-refresh document and six PNG assets. Those files
remain intact in that worktree. No stash, destructive reset or overwrite of the
recovery worktree was used.

Backup before branch/code changes:
`C:/Users/nadin/AppData/Local/Temp/kuzenga-source-backup-20261115-185246/`.
`all-refs.bundle` passed `git bundle verify`; it records complete Git history.
`workspace.tar` includes tracked/untracked source, both worktrees, ignored local
environments/data/uploads, excluding `.git`, inaccessible generated
`.deployment-tools`/`.pytest_cache` and Python bytecode. SHA256:
`6B11E625C698DEDF78FAFAD94F2D0E2AAA65EC7544C23A183C33C013B2C1A4B6`.
Earlier whole-workspace archive attempts failed on protected generated directories;
they were not treated as verified backups. Keep all archives private: local data
and credentials may be present. Restore into a separate directory with `tar -xf`,
clone the bundle for history, and copy recovered working files into that clone;
never extract over an active worktree.

## History and resolution

Fetched all origin branches and `refs/pull/2/head`. Inspected draft PR #2, whose
base is `fix/preview-foundation-20261113` at `0a73eb9` and head is
`fix/mobile-access-production-prep-20261115` at `3b85240`.
`merge-base(main, PR2) = 9b54cff`; `merge-base(foundation, PR2) = 0a73eb9`.
Local recovery's `d6f311f` is already an ancestor of main. The foundation and PR
are sequential descendants, so integration branch
`integration/local-github-20261115` fast-forwarded from main to PR2 without
rewriting history or replaying features. The outstanding recovery edits were then
combined with that complete history; no newest-file assumption was used.

Overlapping template behavior was resolved manually: retain local layout/assets,
preview tabs and mobile marketing menu while preserving PR2's configured school,
student and platform links, info@elevondigitalzw.com and the 2026 footer. Apply the
same result to both existing project and installed-app template locations needed
by serverless packaging. A regression test enforces identical content and links.
Corporate JS keeps the existing calculator and adds the local preview/menu
handlers. CSS and six privacy-edited/brand/photo assets are preserved from local
work. This adds no second application or new rendering architecture.

All implemented school/student/finance/admissions/academic/attendance/assessment
modules and migration history remain. Both dashboard drawers retain shared
keyboard/focus/overlay/desktop behavior. Student login and server-side role and
tenant checks remain. Subscription repair stays superuser-only, transactional,
plan-bound, audited and idempotent, retaining independent grants and original
dates. No unlimited access or catalogue/limit changes were introduced. Exact-host
routing remains opt-in, validates all three hosts, and refuses to forward POST
credentials. Preview and production remain isolated; automatic Git deployment
stays disabled. Historical preview approval text was clarified so it cannot be
read as approval for deployment during this integration.

## Validation

Commands below use `.deployment-tools/venv312/Scripts/python.exe` (Python 3.12),
`VERCEL=1` to prevent loading local dotenv and `DATABASE_URL=sqlite:///:memory:`
for tests/checks. No production connection was supplied.

| Check | Current result |
| --- | --- |
| Product `python -m ruff check .` | Passed, including final added test. |
| Product `python manage.py check --settings=config.settings.test` | Passed, no issues. |
| Product `python manage.py makemigrations --check --dry-run --settings=config.settings.test` | Passed, no changes. |
| Product `python -m pytest -q` | 461 passed, 1 PostgreSQL-only skip, 16 existing Django URLField deprecation warnings. |
| Final `python -m pytest tests/test_public_website.py tests/test_portal_hosts.py -q` | 44 passed, 2 warnings; includes newly added template-sync test after full suite. |
| Product `python scripts/check_deployment.py` | Passed strict synthetic production checks and complete static collection; no DB connection. |
| `node --check static/js/corporate.js` and `node --check static/js/school-layout.js` | Passed. |
| Backend `python -m ruff check .`, `python -m pytest -q` | Passed; 1 test passed. |
| Backend `python manage.py check --settings=config.settings.testing` and `makemigrations --check --dry-run --settings=config.settings.testing` | Passed; no issues/no changes. |
| Isolated browser database `migrate`, `seed_catalog` | Passed locally; synthetic school/admin/student/platform fixtures only, under ignored tooling directory. |
| Edge landing browser | Passed at 320, 360, 375, 390, 430, 768, 1024, 1440px: no page overflow/broken images; preview tabs, reduced motion, menu Escape/focus return passed. Mobile screenshot inspected. |
| Edge calculator | Passed included-module exclusions, Professional 100 learner totals ($65/$28/$0/$93/$279) and custom quote threshold. |
| Edge school and superuser | Real local form logins passed; mobile drawer initial closure, open, inert background, Escape/focus return, overlay dismissal and desktop recovery passed for both. |
| `git diff --check` | Passed before final documentation; repeated before commit. |
| `node scripts/check_vercel_config.mjs` | Blocked: sandbox EACCES, then elevated public schema fetch timed out. No full schema validation claimed. |
| PostgreSQL concurrency acceptance/current integrated PostgreSQL suite | Not run locally; PostgreSQL-only test skipped on SQLite. Existing PR CI is not evidence for this integration commit. Await fresh draft-PR CI. |
| Remote deployment/build and live storage/upload acceptance | Not run: deployment is outside this task. Offline static build passed; no remote-build claim. |

Browser drivers/logs/screenshots and test database stay in ignored
`.deployment-tools/`; they are not committed. Existing PostgreSQL finance guards
were preserved; tests were not weakened to get a passing result.

## Outstanding owner decisions and release gates

- Confirm public domain (`www.elevondigital.com` versus `.zw.com`) and provisional
  client hostname; production example values are proposals, not applied choices.
- Resolve public quotation/pricing text versus the seeded plan feature matrix and
  commercial limits separately. Starter attendance and Standard finance remain
  restricted as currently implemented. See `kuzenga/docs/subscription-access.md`.
- ADR-0001 remains proposed with historical Phase 1 authorization; preserve both
  projects and obtain an owner decision before further consolidation/duplication.
- Complete fresh PostgreSQL CI/acceptance, schema validation, approved staging
  artifact checks and storage upload acceptance before declaring release ready.
- Production DNS, secrets, migration/repair operations, deployment and main merge
  remain on hold for separate approval. Historical infrastructure observations in
  the production-review document were not reverified during source integration.

## Rules and specifications consulted

Root and recovery `AGENTS.md`; rules README; global rules 00 through 10; all module
rules (tenant, authentication, student, admissions, academics, attendance, finance,
examinations, communication, reporting, subscriptions); ADR-0001/0002 and ADR
index; existing deployment, subscription-access and visual-refresh documents;
existing models/services/settings/migrations/tests; verification skill. Some
module rules still call implemented domains planned: preserve existing behavior,
do not infer new requirements from that stale description. No equal-priority
conflict requiring a new architectural or commercial decision was resolved here.

## File review inventory

Each remote diff was compared from its common ancestor, grouped by behavior above.
The following paths retain foundation/PR2 behavior; template overlaps and final
local additions are described above. Files under `backend/`, the commercial
catalogue and business migrations were not changed.

- `docs/operations/kuzenga-production-review-2026-11-15.md`
- `kuzenga/.env.production.example`
- `kuzenga/apps/core/hosts.py`
- `kuzenga/apps/core/public_views.py`
- `kuzenga/apps/core/templates/public/home.html`
- `kuzenga/apps/core/views.py`
- `kuzenga/apps/tenancy/context_processors.py`
- `kuzenga/apps/tenancy/subscription_services.py`
- `kuzenga/config/settings/base.py`
- `kuzenga/config/settings/production.py`
- `kuzenga/docs/deployment.md`
- `kuzenga/docs/subscription-access.md`
- `kuzenga/scripts/check_deployment.py`
- `kuzenga/scripts/check_preview_services.py`
- `kuzenga/scripts/configure_preview_cors.py`
- `kuzenga/static/css/layout.css`
- `kuzenga/static/js/school-layout.js`
- `kuzenga/templates/base/base.html`
- `kuzenga/templates/components/workspace_footer.html`
- `kuzenga/templates/dashboard/index.html`
- `kuzenga/templates/public/home.html`
- `kuzenga/templates/registration/superuser_login.html`
- `kuzenga/templates/superuser/base.html`
- `kuzenga/tests/test_academic_structure.py`
- `kuzenga/tests/test_deployment.py`
- `kuzenga/tests/test_media_and_navigation.py`
- `kuzenga/tests/test_portal_hosts.py`
- `kuzenga/tests/test_public_website.py`
- `kuzenga/tests/test_student_login.py`
- `kuzenga/tests/test_subscriptions.py`
- `kuzenga/tests/test_tenant_admin_profiles.py`
- `kuzenga/vercel.json`

Local additions: corporate CSS/JS refresh; six `static/images/corporate/*.png`
assets named in the visual-refresh report; that report; public regression coverage;
this integration report. No secrets, live environment files, databases, uploads,
cache/build output or browser artifacts are staged. The inherited production
example remains tracked documentation containing example values only.

Dependency metadata check: python -m pip check was blocked because this existing uv-managed verification environment has no pip module. Application imports and executable checks above passed; a fresh CI dependency-installation check remains pending.
