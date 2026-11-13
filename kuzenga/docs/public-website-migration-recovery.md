# Elevon public website and migration recovery checkpoint

Latest status: the owner-authorized local migration application is complete. The original development SQLite database now has all 15 existing pending migrations applied, with verified backup and unchanged domain data. See the final dated section; earlier audit sections describe the pre-application checkpoint.

Date: 2026-11-13. Status: local implementation for review; incomplete release gates.
Branch: `feat/public-ui-migration-recovery`, isolated at `.worktrees/public-ui-recovery`.
Base: `5eec95f` on `chore/vercel-deployment-preparation`. No merge, deployment,
shared-database migration, contract update or payment integration was performed.

## Architecture and ownership

The product runtime is `kuzenga/`, under the recorded Phase 1 authorization in
ADR-0001. ADR-0001 remains Proposed. ADR-0002 accepts preparation only. `backend/`
remains unchanged. Both manage.py files use a package named `config`: always run
commands from the intended project directory and explicitly select test database
configuration. No nested AGENTS.md was found in tracked source. The initial Git
working tree was clean; no other worktrees or agent ownership records were found.
Finance migration files and deployment/settings files were not edited. Integration
must still be coordinated with those workstream owners before using a shared DB.

## Implemented behavior

- Anonymous `/` renders the corporate page; authenticated `/` retains existing
  school/platform routing. `/elevon/` always opens the public page.
- Distinct navy/blue corporate CSS, Manrope with a system fallback, responsive
  sections, official contact links, WhatsApp and the supplied school-office photo.
- School and Student Login reuse `/login/`; existing student memberships and
  redirects are retained. Footer administration uses `/platform/login/`.
- Central public pricing catalogue in `apps/core/pricing.py` supplies the table,
  setup fees, add-ons and client calculator through Django `json_script`. Estimates
  include three-term annual recurring totals, once-off setup, custom quotations,
  API lower-bound prices and exclusion of already-included add-ons. No existing
  plan, subscription, invoice, entitlement or contract record is rewritten.
- New platform-owned DemoEnquiry model, separately generated core migration,
  server-side form validation, consent, CSRF, honeypot, expiring signed form token,
  one-per-minute hashed-IP cache throttle and redirect after successful submission.
  Email uses the configured backend and sender; stored leads survive SMTP failure.
  Notifications contain an enquiry ID without the submitted personal details.
  Read-only lead inspection is restricted to active platform superusers in Django
  admin. No school-facing enquiry list or read endpoint exists.
- Shared school drawer has overlay dismissal, close control, Escape dismissal,
  focus trap/return, inert background, scroll lock, reduced-motion support and
  independent scrolling. Desktop sidebar geometry and navy/gold tokens remain.
- Navigation continues to use the existing permission/entitlement configuration.
  The longest matching route alone receives an active state. Missing commercial
  modules were not added as dead links or granted through frontend logic.

## Database findings

The original development settings were loaded without opening a connection and
confirmed SQLite pointing to the inspected product `db.sqlite3`, with Vercel mode
false. Database sharing/operational ownership remains unconfirmed. It was opened
read-only for metadata and SQLite backup; it was never migrated.

| Product app | Existing applied | Existing pending |
| --- | --- | --- |
| academics | 0001–0004 | none |
| accounts | 0001–0002 | none |
| admissions | 0001 | none |
| assessments | 0001–0002 | none |
| attendance | 0001 | 0002_attendance_foundations |
| core | 0001–0002 | none before this change |
| finance | 0001–0005 | 0006–0019 below |
| students | 0001–0002 | none |
| tenancy (subscriptions included) | 0001–0004 | none |

Pending finance identifiers:

```text
0006_financerequest_financedecision_invoiceadjustment_and_more
0007_financerequest_payment
0008_control_guards
0009_cashsession_cashsubmission_cashreview_financeimport_and_more
0010_alter_financeimport_errors_alter_financeimport_rows
0011_operation_guards
0012_refundclosure
0013_refund_closure_guards
0014_allocationretraction
0015_allocation_retraction_guards
0016_alter_reconciledentry_line_alter_reconciledentry_row_and_more
0017_reconciliation_release_guards
0018_paymentallocation_effective_date
0019_allocation_effective_date_guards
```

New migration: `core.0003_demo_enquiry`, creating only the lead table. The source DB
therefore retains 15 existing pending migrations plus this unintegrated migration.
There is no demonstrated graph conflict, missing model migration, circular
migration dependency or need for a merge migration. These appear to be legitimate
pending application changes; an unapplied marker alone is not corruption.

All existing migrations succeeded on an empty in-memory SQLite database. A verified
SQLite backup was then migrated in the isolated worktree: all 16 pending migrations
succeeded, with no remaining migration plan, no missing model changes, consistent
history, no graph conflicts, passing integrity and foreign-key checks. SHA-256
comparisons across every pre-existing column and row in tenant, user, student,
academic, attendance, finance and audit tables were unchanged. Fingerprints and
row contents were not printed. This protects the observed snapshot; it is not a
production restore rehearsal or proof of PostgreSQL behavior.

Finance guard migrations replace/install triggers via RunPython; SQL inspection
alone cannot show their complete behavior. Existing forward operations include
trigger replacements and field changes, so down-migration must not be assumed safe.
`0018` adds a nullable effective_date without backfilling historical allocations.
No existing migration was edited, faked, deleted or manually marked applied.

The private snapshot remains an ignored `migration-rehearsal-*.sqlite3` in the
isolated product directory. It contains application data: do not commit or publish
it. `scripts/audit_sqlite_metadata.py` performs read-only local inspection;
`scripts/rehearse_sqlite_migrations.py` makes and verifies a new snapshot before
migrating it, checks original domain values, and retains it for review.

## Validation

Commands run with the existing Python 3.12 venv, from the isolated product directory,
with `DATABASE_URL=sqlite:///:memory:` except for the explicitly selected snapshot:

```text
python manage.py check
python manage.py showmigrations
python manage.py migrate --plan
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python scripts/audit_sqlite_metadata.py <original-product-sqlite-path>
python scripts/rehearse_sqlite_migrations.py <original-product-sqlite-path>
python manage.py sqlmigrate core 0003_demo_enquiry
python manage.py sqlmigrate finance 0018_paymentallocation_effective_date
python -m pytest -q
python -m pytest tests/test_public_website.py -q
python -m ruff check apps/core apps/tenancy/context_processors.py scripts/audit_sqlite_metadata.py scripts/rehearse_sqlite_migrations.py tests/test_public_website.py tests/test_entry_routing.py
node --check static/js/school-layout.js
node --check static/js/corporate.js
git diff --check
```

Full suite: 390 passed, 1 skipped before the final lead-admin test was added.
Focused final public suite: 20 passed, including lead administration access.
Existing Django URLField scheme deprecation warnings remain. Ruff and JavaScript
syntax checks pass. The full suite covers tenant isolation, authentication, student,
finance, subscription, audit and dashboard behavior. PostgreSQL-specific coverage
is skipped on SQLite. Python Playwright is unavailable and no browser automation
tool is connected; no browser, visual, keyboard, or requested viewport verification
is claimed. Static responsive styling is not a substitute for those checks.

## Required integration and remaining blockers

1. Coordinate with finance/deployment owners, freeze/review a stable checkpoint,
   identify the shared/staging database and validate its backup/restore procedure.
   Use Django's migration graph order; do not manually reorder finance guards.
2. Review the existing finance/attendance migrations and rehearse on dedicated
   PostgreSQL staging with realistic constraints and representative data. Verify
   trigger enforcement, tenant access, roles and unchanged financial totals.
3. Integrate the additive enquiry migration before exposing the enquiry form. No
   migration should run on requests or builds. A rollback may disable the page;
   do not delete the lead table if it has collected enquiries.
4. Official Elevon logo is missing. The plain typographic company name is
   provisional, not a redrawn official logo. The requested 23-second official-logo
   animation is pending that asset. No substitute logo was generated.
5. Supplied assets are one screenshot and one photo, not two app screenshots. The
   screenshot contains browser tabs, a staff name and school identity. It was
   inspected but not copied into public assets. Provide an approved redacted/cropped
   screenshot and the second app screenshot for the browser mockup showcase. The
   supplied office photograph is used without claiming a client endorsement.
6. Commercial entitlements are not fully implemented. The existing seed command
   gives Starter only academics/students and combines basic and advanced finance
   under one entitlement. Granting finance would expose advanced accounting too.
   Split those capabilities server-side and specify new-contract provisioning
   separately, preserving current customer contracts/grants. Do not run seed_catalog
   to implement this price update. Parent portal, timetable, library, inventory,
   payroll/HR, LMS, advanced analytics, communication automation and commercial API
   integration need implemented-route/entitlement confirmation; no working route
   for those separate products was found. Public plan scope is explicitly labelled
   as a commercial catalogue subject to confirmed module availability.
7. Production email delivery and a shared multi-worker throttle cache are not
   verified. The current default local-memory cache is process-local. Configure
   existing approved infrastructure with the deployment owner before public traffic.
   Establish lead retention/deletion ownership before collecting live enquiries;
   no new retention policy or external service was invented here.
8. Verify browser behavior at 320, 360, 375, 390, 430, 768, 1024 and desktop widths,
   with platform, administrator, teacher, bursar and student roles. Check drawer
   focus, scroll, overlay, resize, reduced motion, tables/forms and calculator totals.
9. Confirm production backup/data-export arrangements before making operational
   promises; none were provisioned by the public pricing update. Obtain explicit
   approval before merge, deployment or any production database operation.

Production migration/release readiness: **not established**.

## Files and consulted instructions

Modified: core admin/models/views; tenancy context processor; config URLs; school
layout CSS/JS; base template/sidebar; entry routing test. Added: pricing catalogue,
public form/view/template/CSS/JS, office photo, enquiry migration, public website
tests, SQLite metadata/rehearsal scripts and this checkpoint report.

Consulted root AGENTS.md; `.codex/rules/README.md`; globals 00–10; module index and
all module guardrails (tenant, authentication, student, admissions, academics,
attendance, finance, examinations, communication, reporting, subscriptions);
ADR-0001 and ADR-0002; canonical-backend architecture and comparative audit;
existing school frontend consolidation, finance management and migration tests;
Sites SKILL.md with local-only, presentation and local-preview guidance. Some
module rules still describe implemented domains as planned; existing code and
owner task scope were inspected instead of inventing absent workflows. No ADR
status or approved security boundary was changed.

Final rendered-page/routing verification after the last template changes:
`python -m pytest tests/test_public_website.py tests/test_entry_routing.py -q`:
27 passed, 2 existing deprecation warnings. `git diff --check` passed. Original
tracked files remain unchanged; the original checkout reports only the new
untracked `.worktrees/` directory. Changes in the feature worktree are uncommitted
for review and must be integrated explicitly; do not accidentally add the worktree
folder from the original checkout.

## Explicit schema-drift audit

The development SQLite database was compared read-only against a disposable
in-memory database rebuilt using exactly its 41 recorded applied migrations,
not the newest models. This distinction prevents legitimate pending migrations
from being reported as schema corruption.

Result: all 268 reference schema objects match. No missing objects, unexpected
objects, or changed definitions were found. Comparison includes tables, column
order/types/nullability/defaults/primary keys through SQLite table_xinfo, foreign
keys, indexes and uniqueness, SQL constraint definitions (including CHECK), and
trigger definitions. Internal SQLite bookkeeping and the migration recorder table
itself are excluded. The 15 existing pending migrations remain pending changes,
not detected schema drift. No repair or fake migration is indicated by this audit.

Command from the isolated product directory:

```text
python scripts/audit_sqlite_schema.py <original-product-sqlite-path>
python -m unittest tests.test_sqlite_schema_audit -v
python -m ruff check scripts/audit_sqlite_schema.py tests/test_sqlite_schema_audit.py
```

The three audit tests pass, covering identical schemas despite different data,
missing indexes/triggers plus an added column, and altered foreign-key/CHECK
constraints. SQL definition comparison normalizes whitespace only; an equivalent
manually rewritten definition may be reported for review rather than automatically
classified as corruption. The tool exits nonzero on differences and never repairs
them. This audit does not verify PostgreSQL, uninspected environments, data-level
business invariants, or whether an applied migration file was edited historically.

Additional files: `scripts/audit_sqlite_schema.py` and
`tests/test_sqlite_schema_audit.py`. Existing database/security/testing rules and
the earlier architecture decisions continue to apply; no shared source or migration
file was modified for this follow-up.

## Owner-authorized local migration application (2026-11-13)

The owner subsequently instructed: "do migrations". The 15 existing pending
migrations were applied to the original checkout's confirmed local development
SQLite database using the original checkout's code/settings. This supersedes the
earlier checkpoint statement that the source database was left unmigrated.
No production/PostgreSQL database or existing migration file was changed.

Before application, the migration graph/history and exact scope (15 forward
attendance/finance migrations) were checked. A fresh SQLite backup was created:
`kuzenga/db.before-authorized-migrations.20261113T012912426728Z.sqlite3`
(relative to repository root). Backup integrity, foreign keys, domain fingerprints
and an in-memory restore were verified before applying any migration.

Applied: `attendance.0002_attendance_foundations` and `finance.0006` through
`finance.0019`, preserving Django dependency order. All succeeded. Post-application
`check`, `showmigrations`, `migrate --plan`, `makemigrations --check --dry-run`,
SQLite integrity and foreign-key checks passed. No migrations remain pending in
the original checkout, and no model migrations are missing. Pre-existing columns
and rows across finance, tenant, accounts, academics, student, attendance,
assessment, admission and core tables have unchanged fingerprints.

`core.0003_demo_enquiry` remains separate in the feature worktree and was not
applied to the original database, because its feature code is not integrated.
The verified backup remains local and ignored; do not commit or publish it.
No automatic rollback was performed or scheduled. Any future restore must be
coordinated to prevent loss of records created after this backup.

The repeatable, guarded application procedure is recorded in
`scripts/apply_local_migrations.py` in the feature worktree. Ruff passes for it.
Rules consulted remain globals 00–10, database/security/testing guidance,
finance/attendance/tenant module rules and ADRs 0001/0002. Existing broad
architecture approval and production migration readiness remain unresolved.

Final post-application schema audit: replayed all 56 recorded migrations in a
disposable in-memory reference; all 401 schema objects match, with no missing,
unexpected or changed objects. No schema drift was detected after application.

## Public root routing and owner-authorized integration

The owner requested the landing page at `http://127.0.0.1:8000/` and explicitly
requested committing/pushing to the finance branch and merging into main.
Root `/` now always renders the corporate page, including for signed-in users.
The named `dashboard` route moves to `/dashboard/`; Django's configured named
login redirect and existing sidebar links follow it. `/elevon/` remains an alias.
Platform login retains its existing platform-directory redirect. No authentication
or tenant authorization was replaced. This supersedes the earlier anonymous-only
root design and the previous no-merge authorization boundary for these changes.
No deployment was authorized; tracked Vercel Git deployment remains disabled.

Verification before integration: 394 tests passed, 1 PostgreSQL-specific test
skipped on SQLite; focused routing/public/portal suite 32 passed. Local HTTP checks
returned 200 for the root, corporate CSS/JS/photo, school login and platform login.
These are HTTP checks, not browser visual verification. Ruff and diff checks pass.
The new enquiry migration must accompany the landing-page code in the active
checkout and be applied locally with a freshly verified backup. Existing public
branding, module-entitlement and production-readiness limitations remain as above.
