# Module 12 — finance implementation checkpoint

## Scope and recovery

**Current checkpoint: core workflows, financial operations, allocation retraction, controlled corrections and bounded financial exports are implemented. Read the final hardening acceptance checkpoint below for executed verification and remaining production-acceptance conditions.**
The owner's full Module 12 prompt supplies the finance specification. Neither existing
Django project had a school finance app or ledger. Existing subscription billing statuses
are platform subscription controls, not student payments, and were left unchanged.

Reused `TenantScopedModel`, tenant context/middleware, memberships, permission registry,
the existing `finance` entitlement, student identities, append-only `AuditEvent` service,
school base layout, school headings/buttons and shared form rendering. No replacement
student, guardian, staff, tenant, user, academic-year or term models were introduced.
The reference `design/references/school-admin-dashboard.png` is absent. Existing visual
components provide the navy/gold school styling. Platform navigation and separate login
portals remain unchanged. Existing uncommitted attendance, assessment, frontend and
deployment work was preserved.

## Foundation delivered

- Tenant-specific currencies with configurable precision (0–4 decimal places); configure
  USD and ZiG separately. No external rate fetching, payment provider, or funds movement.
- Configurable chart of accounts: assets/liabilities/equity/income/expenses, purpose
  mappings for cash, bank, mobile clearing, receivables, tuition, boarding, transport,
  other income, concessions, refunds, unallocated money, opening balances and bad debt.
- Nonoverlapping accounting periods, open/closed state and date validation on posting.
- One-to-one student financial identity with PROTECT deletion, linking the existing
  student record. Phase 2 adds canonical enrolment integration, historical account
  synchronisation, an account directory and currency-specific statements.
- Journals and lines, exact Decimal posting validation, tenant-scoped references and
  idempotency keys, original source references, immutable rate/effective-date metadata.
- Atomic append-only posting, linked full reversals, same-person reversal approval
  prevention, exact student balance calculation separated by currency.
- School chart/configuration forms, manual non-student journal posting screen, posted
  journal lookup, filtered general ledger/account movement trial report, and audit trail.
- Finance sidebar item points to an actual registered school route; no placeholder links
  for the unimplemented later phases.

## Accounting contract

Each journal uses exactly one currency. It must have 2–1000 lines, every line has exactly
one positive debit or credit, and total debits equal total credits. Amount inputs must be
Decimal/integer/decimal strings, never binary floats; nonfinite, negative, oversized and
overprecision values are rejected rather than silently rounded. The supported per-line
amount is less than 100,000,000,000 currency units, capped to keep SQLite scaled-integer
balance checks within range. Currency precision cannot change once used in the ledger.

Receivable lines require the existing student's financial account; other accounts cannot
carry a student dimension in this checkpoint. Thus student balances are debit minus credit
on the receivable ledger, per currency, with no mutable balance counter. Aggregate reports
sum retrieved Decimal values in Python to avoid SQLite's floating-point SUM behavior.

Posted rows never change or disappear. A reversal is a new journal with swapped debit/
credit lines in the original currency and an explicit one-to-one link to the original.
The original remains posted; balances include both original and offset. Reversals require
a reason and a different user's approval. Exchange metadata is retained; paired explicit
cross-currency conversion workflows are still pending and no automatic conversion occurs.

`post_journal`, `reverse_journal`, `configure` and `student_account` in
`apps.finance.services` are application write boundaries. They validate active school
membership and entitlement and use an atomic transaction with a tenant row lock. Reusing
an idempotency key returns its existing posted journal only when the normalised payload
fingerprint agrees; conflicting retries fail. Posted account codes/types/purposes and
period dates are protected. Closed periods reject postings.

All ledger ORM update/delete/bulk-write operations are denied. Custom database triggers
also reject posted header changes, line updates/deletes, additions to posted journals,
unbalanced posting, wrong-tenant relationships, and changes to used currency/account
identities. Headers are created unposted and completed inside the same atomic service
transaction; only posted entries enter reports. Direct database administrators retain
the power to disable triggers; restrict database credentials and operational privileges.

Database guards use scaled integer arithmetic for SQLite journal balance checks and
PostgreSQL NUMERIC arithmetic in the PostgreSQL implementation. PostgreSQL line inserts
lock the parent journal. **These PostgreSQL guards and concurrency behavior have not been
executed or verified against PostgreSQL.** SQLite tests cannot establish concurrency safety.

## Permissions

Use the existing role registry without changing AUTH_USER_MODEL or role identities:

| Existing role | Foundation permissions |
| --- | --- |
| Owner/principal | Existing wildcard permissions, subject to same-person reversal denial |
| School admin | finance.view, finance.configure, finance.approve, finance.fees |
| Bursar | finance.view, finance.post, finance.fees |
| Teacher/HOD/staff/guardian/student | No finance permissions |
| Platform superuser | Explicitly rejected by finance service authorisation |

Each service re-reads membership/user state; a stale inactive membership is insufficient.
Cashier/accountant-specific delegation and guardian-to-student portal identity mapping
are not added speculatively. They remain later-phase responsibilities. Current school
admins oversee/configure/reverse; bursars record journals. Sensitive reversal approval
cannot be performed by the journal's creator even if they later become an owner.

## School URLs

With a local server running on port 8000:

- `http://127.0.0.1:8000/finance/` — foundation overview and currency-separated control totals.
- `http://127.0.0.1:8000/finance/accounts/` — chart of accounts.
- `http://127.0.0.1:8000/finance/settings/currencies/` — configure currencies.
- `http://127.0.0.1:8000/finance/settings/accounts/` — configure chart accounts.
- `http://127.0.0.1:8000/finance/settings/periods/` — create accounting periods.
- `http://127.0.0.1:8000/finance/journals/new/` — bursar journal entry.
- `http://127.0.0.1:8000/finance/journals/<journal_uuid>/` — posted journal.
- `http://127.0.0.1:8000/finance/ledger/` — general ledger and account movement report.
- `http://127.0.0.1:8000/finance/audit/` — financial audit history.

Ledger filters: `currency=<currency_uuid>&start=YYYY-MM-DD&end=YYYY-MM-DD`.
Invalid filters produce form errors and no results. The trial report is explicitly labelled
as movements within selected dates; it is not a statutory financial statement or a claim
about fees billed/collected. The foundation dashboard shows actual ledger control totals,
not fabricated business KPIs.

## Files and migrations

New files: `apps/finance/{apps,models,services,forms,views,urls}.py`, package markers,
`migrations/0001_initial.py`, `migrations/0002_ledger_guards.py`, eight `templates/finance/`
templates, `tests/test_finance_foundation.py`, and this document.
Narrow integration additions: installed app in `config/settings/base.py`, school routes
in `config/urls.py`, finance permissions in `apps/tenancy/permissions.py`, and the school
sidebar registry in `apps/tenancy/navigation.py`.

The migrations create only finance tables/constraints/triggers. Existing data/migrations
are not reset or flushed. The guard migration is intentionally irreversible: do not unapply
it as a rollback shortcut. Use a reviewed forward migration and backup/recovery plan for
any later ledger schema change. No sample financial records are inserted automatically.

## Verification commands

Run from `kuzenga/`, the directory containing `manage.py`:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate finance --plan
python manage.py migrate finance
python -m ruff check apps/finance tests/test_finance_foundation.py
python -m pytest tests/test_finance_foundation.py -q
python -m pytest tests/test_finance_foundation.py tests/test_access_and_entitlements.py tests/test_tenant_isolation.py tests/test_assessments.py tests/test_student_management.py -q
```

Back up the selected database before applying migrations. Running from the repository's
outer directory can select a different relative SQLite database; verify the configured
database before migration. Do not apply unrelated pending attendance migrations as part
of this foundation checkpoint.

## Verified Phase 1 checkpoint (2026-11-10)

- `python manage.py check`: passed; no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `python -m ruff check apps/finance tests/test_finance_foundation.py`: passed.
- The combined regression command above: **71 passed**, including **19 finance tests**;
  two existing Django URLField default-scheme deprecation warnings.
- Tests cover Decimal limits/precision, 0.10 + 0.20 balance validation, duplicate request
  replay/conflicts, currency separation, reversals, same-person approval denial even with
  owner permission, closed periods, raw-SQL immutability and unbalanced-post rejection,
  tenant/entitlement restrictions, superuser denial, request-time scoped form choices,
  and an actual journal-form POST with repeat-submit duplicate prevention.
- Verified selected database: local SQLite `db.sqlite3`. Created
  `db.pre-module12.20261110215042.sqlite3` with SQLite's backup API before migration.
- Reviewed the generated SQL and custom trigger migration. Applied `finance.0001_initial`
  and `finance.0002_ledger_guards` only; 11 SQLite guards are installed. No unrelated
  pending migration was applied. Existing financial history was not reset.
- Compared complete rows in 46 pre-existing data tables with the backup: unchanged.
  Excluded Django migration/content-type/permission metadata from that comparison;
  new model metadata is expected. Foreign-key check returned no violations.
- Working database contains zero finance journals. Automated tests did not insert
  demonstration transactions into the working school database.
- PostgreSQL trigger execution/concurrency and browser visual/accessibility verification
  remain unrun. This checkpoint is not a claim of complete Module 12 production readiness.

## Phase 2 additions (2026-11-11)

Added a searchable student financial account directory and per-currency account statements
with date, academic-year and term filters, opening/closing balances, available credit and
running balances. Historical accounts remain accessible after student withdrawal. The
student profile displays balances only when finance services authorise the viewer.

The existing enrolment service now calls a narrow finance-owned account-creation helper.
It creates identity only when the school has Finance enabled; it never posts fees.
An explicit administrator POST action synchronises missing accounts for historical
enrolments and upgrades. Repeating synchronisation creates no duplicate identities.
Other enrolment writers should use the existing enrolment service; historical/direct
placements can be covered by the synchronisation action.

Added immutable fee versions with charge codes, currency/precision, amount, income mapping,
academic year/term, grade/class, boarding/day and student-category selectors, optional
service flags, effective dates and due dates. Same-code rules with intersecting student
scopes and effective dates are rejected under the existing tenant posting lock. Separate
grade/class scopes and nonoverlapping replacement versions are supported. The service
does not classify students into boarding/category/service groups or post invoices yet.
Administrators and bursars have `finance.fees`; chart/currency configuration remains
administrator-only. Fee versions cannot be edited/deleted through model/queryset APIs.
Fee overlap/concurrency is not claimed verified on PostgreSQL.

New routes:

- `/finance/students/`: directory, search and authorised account synchronisation.
- `/finance/students/<account_uuid>/`: statement; requires a currency selection.
- `/finance/fees/`: fee version directory.
- `/finance/fees/new/`: create a fee version.

New files: `apps/finance/student_accounts.py`, `migrations/0003_feerule.py`,
`tests/test_finance_accounts.py`, `templates/finance/student_accounts.html`,
`statement.html`, `fees.html`, `_student_summary.html`. Existing finance models/forms/
services/views/URLs/nav and student enrolment/profile integration receive scoped changes.
The original two ledger migrations and posted records are untouched.

Verification: `python -m pytest tests/test_finance_accounts.py tests/test_finance_foundation.py tests/test_student_management.py tests/test_admissions.py -q` — **94 passed**, two existing
Django URLField deprecation warnings. Django system/migration checks and Ruff passed.
Later workspace changes added upload code requiring the repository-pinned `botocore`;
after an approved dependency installation, the final checks passed. No upload code was
changed as part of Finance.

Backed up local SQLite as `db.pre-module12-phase2.20261111030612.sqlite3`, reviewed and
applied only `finance.0003_feerule`. Compared all rows in 52 pre-existing data tables:
unchanged; foreign-key checks returned no violations. Fee configuration and account
synchronisation were not run against real school data; no demonstration charges were
created. Original ledger migrations and records remain intact. PostgreSQL and visual
browser verification remain unexecuted.

## Core finance workflows (2026-11-11)

### Billing

`apps.finance.workflows` applies the existing immutable fee version to enrolled students
within its effective dates, academic year, term, grade/class and explicitly selected
boarding/category/optional-service scope. Billing can target an individual, selected
students or an entire eligible cohort, with optional class restriction. A signed preview
freezes the exact reviewed cohort for 15 minutes and is bound to the school membership.
An atomic posting run creates at most 200 invoices; larger schools should bill by class.

Each fee version is billed once per student, enforced by a natural database key. Retries
return existing invoices; changing a previously used posting date/period is rejected.
Invoice numbers use a tenant-locked sequence. Due dates and amounts come from the fee
version; student name/admission, fee description and eligibility choices are snapshotted.
Posting debits student receivables and credits the fee's configured income account.
Invoice settlement is derived from active allocations rather than mutable paid counters.

### Payments and allocations

Recording cash, bank transfer/deposit, EcoCash, OneMoney, InnBucks, POS or other recorded
payments creates an immutable pending record only. Confirmation creates an immutable
decision and balanced journal: debit the configured cash/bank/mobile asset account,
credit that student's receivable account, in the payment currency. An electronic payment
requires explicit verification and a private verification reference; no gateway is called.
Rejected payments never affect the ledger and cannot later be silently confirmed.

Payment request keys are tenant-scoped and payload fingerprinted. Provider references are
normalised and unique per school/method, including rejected/reversed history. Cash retries
are protected by the form/service idempotency key; no heuristic claims to identify two
separately entered physical cash payments. Payment dates must fit the selected open
accounting period when confirmed; unposted records have no student balance effect.

Confirmation can allocate oldest-due invoices first or leave student credit unallocated.
Manual allocation supports full/partial application and one payment across invoices.
Multiple payments can settle one invoice. The service and database reject excessive,
cross-student, cross-currency, reversed or mismatched-control-account allocations. A
payment/invoice pair has an immutable allocation; a repeated equal allocation is idempotent,
and changing that allocation requires a controlled payment reversal, not an overwrite.
Overpayments remain a negative receivable balance (student credit); they are not silently
converted or reclassified to statutory liability accounts. Future liability presentation
and exchange treatment require an explicit school accounting policy.

### Receipts and corrections

Confirmation atomically issues a unique tenant-sequenced receipt, with school branding,
student/account identity, amount/currency, method, references, date/time, original cashier,
confirming user, allocation snapshot and balance at issue. The HTML receipt and PDF
history remain accessible. PDF generation uses existing Pillow; every printed copy is
labelled DUPLICATE COPY and retains its original number. Reprinting is audited and served
private/no-store. No extra rendering service or payment integration is introduced.

A different authorised approver must reverse a confirmed payment; neither its recorder
nor its confirmer may approve their own reversal. The existing ledger reversal service
creates the exact offsetting journal in the same currency. Original payments, receipts
and allocation rows remain immutable. Invoice balances exclude allocations backed by a
reversed journal, and the original receipt is displayed/printed VOID. Repeating a reversal
returns the existing offset and does not reverse money twice. Approval records accounting
correction only; no funds are moved. Issued receipts cannot be independently deleted/voided
while leaving their payment posted.

### Debt and collections

Debtors show unpaid invoices, overdue dates and configurable ageing cutoffs (default
30/60/90 days), currency/date/minimum filters, and per-currency gross invoice totals.
Invoices not yet due are labelled Current. Historical ageing includes only invoices,
payments and reversals effective by the selected as-of date. Net student receivable
balances are shown separately and also include opening/manual ledger entries; negative
balances are credit. Unallocated credit must be considered before collecting gross
invoice debt. Currencies are never combined.

Payment arrangements require a reason and 1–24 positive instalments totalling current
invoice debt. Amendments explicitly supersede the previous immutable schedule. Baseline
paid amounts prevent earlier payments from being counted twice against a new plan;
missed instalments and settled plans are derived from the invoice allocation history.
Collection follow-ups retain actor, notes, promise date and idempotency key. These are
private records, not claims of a delivered notification. Collection reports group actual
payment records by currency/month/method/current status, separating confirmed, pending,
rejected and reversed amounts. They are not a bank cash-movement or statutory statement.

### URLs added

All paths below use the existing school portal and active tenant. Prefix with
`http://127.0.0.1:8000` for a local server on port 8000.

| Path | Purpose |
| --- | --- |
| `/finance/billing/` | Individual/bulk preview and posting |
| `/finance/invoices/` | Invoice directory, paid and outstanding balances |
| `/finance/invoices/<invoice_uuid>/` | Invoice, allocations, plans and collection history |
| `/finance/payments/` | Recorded payment directory/status |
| `/finance/payments/new/` | Record pending payment |
| `/finance/payments/<payment_uuid>/` | Confirm/reject, allocate credit, receipt link |
| `/finance/payments/<payment_uuid>/reverse/` | Separate-person authorised reversal |
| `/finance/receipts/` | Search receipt/payment/provider reference |
| `/finance/receipts/<receipt_uuid>/` | Original receipt and void status |
| `/finance/receipts/<receipt_uuid>/print.pdf` | Branded duplicate PDF copy |
| `/finance/debt/` | Student balances, gross arrears and invoice ageing |
| `/finance/arrangements/new/` | Create/amend instalment arrangement |
| `/finance/follow-ups/new/` | Collection notes and promises |
| `/finance/collections/` | Currency-separated collection reporting |

Existing `/finance/students/<account_uuid>/` statements reflect every posted invoice,
confirmed payment and reversal, including historical records after withdrawal. Existing
school Finance navigation includes these actual routes; platform navigation is unchanged.

### Files, migrations and controls

Added models: `DocumentSequence`, `Invoice`, `Payment`, `PaymentDecision`,
`PaymentAllocation`, `Receipt`, `PaymentArrangement`, `DebtFollowUp`. Added services in
`workflows.py`, scoped forms in `workflow_forms.py`, school views in `workflow_views.py`,
PDF generation in `receipt_pdf.py`, core workflow tests and finance templates. Existing
ledger services, tenant identity, academic/student/staff models and login portals are reused.

`0004_invoice_debtfollowup_payment_paymentarrangement_and_more` creates new tables and
uniqueness/amount constraints. `0005_core_document_guards` adds SQLite/PostgreSQL source
document tenant checks, allocation limits, journal/source consistency and append-only
guards (including existing fee versions); it does not rewrite ledger history. The new
guard migration is intentionally irreversible. Future schema changes need reviewed forward
migrations because SQLite table reconstruction can drop custom triggers. PostgreSQL guards,
parent/tenant lock concurrency and operational database permissions still need real
PostgreSQL verification; no concurrency claim is based on SQLite tests.

Roles reuse the current registry: bursars/owners post invoices and payments; school admins
review/report and approve reversals; admins/bursars manage debt arrangements/follow-ups.
Owners also remain subject to same-person reversal restrictions. Platform superusers do
not acquire automatic finance access. Server permissions, tenant scoping, CSRF, atomic
posting, immutable source records and the existing audit facility remain authoritative.

### Manual verification

1. Configure an open academic/accounting period, USD currency, student receivable asset,
   tuition income and cash/bank/mobile asset accounts. Enrol an existing student.
2. Configure a USD 150 fee and use `/finance/billing/` to preview and post it for that student.
3. As a bursar, record USD 50 cash at `/finance/payments/new/`, then confirm it with oldest-
   invoice allocation. Open the receipt/PDF; the invoice and statement should show USD 100.
4. Record/confirm USD 100. The invoice is settled and student balance is USD 0.
5. As a different school admin/approver, reverse the USD 50 payment with a reason and open
   accounting period. Invoice/statement debt returns to USD 50; original receipt is void,
   but original payment, receipt, allocations and all balanced journals remain present.

Automated verification covers this entire path, duplicate billing/payment/confirmation,
bulk enrolment billing, overpayment credit, manual partial allocation, wrong-currency/
wrong-student allocation, cross-tenant record/PDF access, electronic verification, forbidden
reversals, arrangement amendment, raw-SQL immutability and historical ageing. Test commands:

```powershell
python -m pytest tests/test_finance_workflows.py -q
python -m pytest tests/test_finance_workflows.py tests/test_finance_foundation.py tests/test_finance_accounts.py tests/test_student_management.py tests/test_admissions.py tests/test_access_and_entitlements.py tests/test_tenant_isolation.py -q
python manage.py check
python manage.py makemigrations --check --dry-run
python -m ruff check apps/finance tests/test_finance_workflows.py
```

Initial combined regression: 117 passed, two existing URLField deprecation warnings.
Selected local database was verified as SQLite `db.sqlite3`. Backed up as
`db.pre-module12-core.20261111034927.sqlite3` before applying only finance migrations 0004
and 0005. Final verification after report/precision/status changes: **117 passed**, two
existing URLField warnings; Django check, migration consistency, Ruff and scoped whitespace
checks passed. All rows in **53 pre-existing data tables were unchanged**, excluding Django
migration/content-type/permission metadata. Foreign-key checks returned no violations.
There are 35 finance guards installed in SQLite. The working database contains zero
invoices, payments or receipts: all financial workflow tests used isolated test data.

### Remaining limits outside the four core workflows

Historical core checkpoint: the operations listed as absent in the next paragraph
were subsequently implemented as recorded in the operations recovery checkpoint below.

No live payment gateway, fund transfer, automatic messages, statutory financial statement,
cash-up, bank-statement reconciliation, refund disbursement, concession/write-off workflow,
spreadsheet import or automatic currency conversion is implemented. Additional invoice
approval queues, multi-line/pro-rata/scheduled billing, credit-note cancellation and
allocation retraction/reallocation remain later work. Bulk runs are capped at 200 students;
collection plan/note panels show the latest 100. Browser responsive/accessibility review,
PDF visual inspection, large-volume profiling and PostgreSQL concurrency tests remain
unexecuted. Raster PDFs are printable but not tagged/accessibility-certified; font coverage
depends on installed fonts. Provider references remain reserved after rejection/reversal;
an explicit provider-reference correction workflow is not implemented.

## Finance operations continuation — Phase 1 concessions

Implemented fixed/percentage discounts, scholarships, bursaries, sibling/staff-child
concessions and waivers as immutable `FinanceRequest`/`FinanceDecision` records. Requests
retain eligibility attestation, a private supporting reference, effective dates, original
invoice and unique benefit code. Eligibility is reviewed by an authorised person; no
unsupported automatic sibling/HR classification is inferred from existing records.

A different school approver must approve/reject. Approval posts a balanced debit to a
configured concession expense/contra-income account and credit to the invoice's student
receivable account. Percentage benefits use the original invoice amount, Decimal and
currency-precision ROUND_HALF_UP. Reductions are capped at current unpaid invoice debt;
paid-charge cancellation/reallocation is not silently inferred. Multiple benefits cannot
reduce debt below zero. Benefit/reference codes are unique per invoice, even after a
rejection or reversal, and idempotency keys reject changed payloads.

`InvoiceAdjustment` keeps invoice balances/ageing in step with the unchanged original
invoice and the authoritative ledger. Original invoices, payments and receipts are never
rewritten. New control guards supplement existing allocation limits so debit/credit notes
also respect adjusted invoice capacity. Control accounting journals require
`finance.approve`; this does not give school administrators general cashier posting access.

Phase 1 focused checkpoint: `python -m pytest tests/test_finance_controls.py tests/test_finance_workflows.py -q`
— 16 passed, two existing URLField deprecation warnings. This includes initial refund
approval/disbursement smoke coverage; later phases are not declared complete by this result.

School URLs (prefix `http://127.0.0.1:8000` for local testing): `/finance/controls/`,
`/finance/controls/new/`, `/finance/controls/<request_uuid>/`,
`/finance/controls/<request_uuid>/decide/`, `/finance/controls/<request_uuid>/reverse/`.
Finance navigation links to Concessions & controls; the platform interface is unchanged.

Added `controls.py`, `control_forms.py`, `control_views.py`, two control templates and
`tests/test_finance_controls.py`; extended existing finance models, invoice balance
calculation, allocation validation, journal permission selection and registered school URLs.
Migrations 0006–0008 are additive control/source-link/guard migrations; application status
and final data verification will be recorded when the local migration checkpoint is taken.

## Remaining phases — precise continuation list

1. **Phase 2 follow-ups:** automatic accounts cover the canonical enrolment service;
   historical/direct placement writers use explicit synchronisation. Billing now validates
   academic/enrolment scope and explicit boarding/category/optional-service attestations;
   it does not infer student classifications. Replacing an overlapping future fee requires a designed,
   audited supersession workflow; current replacements must have nonoverlapping dates.
2. **Phase 3 extensions:** multi-line/pro-rata/scheduled billing, separate approval queues,
   credit-note cancellation. Core individual/bulk invoices and duplicate prevention are complete.
3. **Phase 4 extensions:** richer evidence storage and controlled allocation retraction/
   reallocation/provider-reference correction. Core recording, confirmation, allocation,
   credit, receipts and payment reversal are complete.
4. **Phase 5 extensions:** pending notification/reminder workflows and further debt/academic
   cohort reporting. Core ageing, arrangements, follow-up history and collections are complete.
5. **Financial-control extensions:** paid-charge cancellation and allocation release,
   automatic concession eligibility, delegated cashier/accountant roles, and amendment
   workflows after a rejected cash-up or an incorrect approved reconciliation match.
   Concessions, refund approval/disbursement/closure, notes, write-offs, cash-up and
   independent statement matching are implemented below.
6. **Import extensions:** XLSX support, downloadable exception reports and owner-defined
   source retention/archival. Controlled private CSV opening/statement imports are implemented.
7. **Reporting extensions:** dashboard class/grade selectors, additional business CSV/PDF
   reports, dedicated financial statements and explicit currency exchange transactions.
   Currency/date/year/term filters and class/grade debt breakdowns are implemented.
8. **Frontend extensions:** further reporting/settings and browser/accessibility review.
   Operations screens and Finance navigation are implemented.
9. **Phase 10 extensions:** the core end-to-end billing/payment/receipt/settlement/reversal
   workflows are tested. Remaining extension domain/security tests; PostgreSQL migration,
   trigger, deadlock/retry and concurrent idempotency/allocation/numbering tests; narrow/
   wide browser, accessibility and PDF inspection. Browser verification is not completed.

## Finance operations recovery checkpoint (2026-11-12)

Recovered the existing operations implementation without rebuilding core billing,
payments, allocations, receipts or debt management. Inspection included Git status/diff,
all finance models/services/views/forms/tests/migrations, the refund query changes and
`templates/finance/import.html`. Finance files remain untracked in the existing working
tree; unrelated changes were preserved. The earlier Phase 1 and core results above are
historical checkpoints, not the current feature inventory.

### Implemented operations

- **Concessions:** fixed/percentage discounts, scholarships/bursaries, sibling/staff-child
  concessions and waivers; eligibility attestation, dates, supporting references, independent
  decisions, duplicate benefit prevention and balanced invoice adjustments.
- **Corrections:** credit/debit notes and bad-debt write-offs against unpaid invoices.
  Immutable requests/decisions and linked reversing journals preserve original documents.
- **Refunds:** requests linked to original confirmed payments; independent approval reserves
  available source-payment credit without posting money. Separate evidenced disbursement
  posts debit student receivables / credit cash or bank. Independent closure cancels an
  unused approval or reverses its disbursement, retaining every record and releasing the
  reservation. Allocation checks prevent spending reserved/refunded source credit.
- **Cash-up:** per-cashier/date/currency/account sessions, opening float, ledger-derived
  expected cash, actual count, shortage/overage reasons, frozen submission and independent
  supervisor review. Backdated postings to submitted sessions are rejected. Differences
  remain visible and do not silently create write-offs.
- **Reconciliation:** configurable bank/mobile asset accounts; private UTF-8 CSV source,
  duplicate fingerprints, valid/invalid previews and independent import decisions. Exact
  account/currency/signed-amount matches require proposal plus independent approval.
  Unmatched rows and subsequently reversed matches remain exceptions. Import/matching
  never automatically creates or confirms student payments.
- **Opening balances:** existing admission-number matching, separate USD/ZiG rows, signed
  debit/credit totals, validation errors, independent approval and balanced opening journals.
  Existing-activity acknowledgement is required where applicable. Per-student/currency
  opening entries cannot be imported twice; existing balances are never overwritten.
- **Dashboard:** real tenant-scoped billed/net-billed, collections, refunds, debt/credit,
  overdue debt, cohort settlement rate, daily/term collections, ageing, monthly/method
  collections, class/grade debt and unallocated credit, always separated by currency.
  Monetary filters use year/term/currency/date; debt is cumulative as of the end date.
  Current school-wide approval/refund/exception counts are explicitly labelled separately.
  Gross overdue invoices can differ from net debt where unallocated student credit exists.

### Recovery fixes and verification

Recovered refund detail joins include disbursement, closure and reversal records; the
pending-refund dashboard query excludes closed authorisations. Import exceptions remain
reviewable/rejectable while invalid sources cannot be approved. During recovery the import
preview was corrected to hide projected additional balances after review, avoiding an
apparent second opening charge. A regression assertion covers pending and approved views.
The review link text was also repaired. No financial data was rewritten.

Initial recovered finance suite: **49 passed**, two existing Django URLField deprecation
warnings. Syntax compilation, Django system check, migration consistency and Ruff passed.
Final broader regression: **78 passed**, two existing URLField deprecation warnings:

```powershell
python -m pytest tests/test_finance_foundation.py tests/test_finance_accounts.py tests/test_finance_workflows.py tests/test_finance_controls.py tests/test_finance_operations.py tests/test_assessments.py tests/test_attendance_foundations.py tests/test_school_portal_integration.py -q
```

No tests failed. Final `manage.py check`, `makemigrations --check --dry-run`,
`compileall` and scoped Ruff checks passed; `migrate finance --plan` confirms only
0006–0013 are pending. The broader run includes the recovery preview regression.
All **32 finance templates** also compiled successfully through Django's template loader.

Changes belong to `apps/finance/{models,services,workflows,controls,control_forms,
control_views,operations,operation_forms,operation_views,dashboard,dashboard_views,urls}.py`,
finance templates/navigation, `tests/test_finance_controls.py`,
`tests/test_finance_operations.py` and this document. Recovery-only changes are the
import view/template, opening-preview regression assertions and this status update.

Migrations **0006–0013** add control records, original-payment linkage, operational/import
records, refund closure and database guards. They are generated and exercised in isolated
SQLite test databases; **they remain unapplied to the working local database** (0001–0005
are applied). Guard migrations intentionally have no automatic rollback. No original
migration was reset, and no working database record was changed by recovery.

### Exact school URLs

Use the school's configured origin; local examples use `http://127.0.0.1:8000`.
Sign in at `/login/` and select an authorised school membership.

| Screen | URL path |
| --- | --- |
| Finance dashboard | `/finance/` |
| Student financial accounts | `/finance/students/` |
| Statement | `/finance/students/<account_uuid>/` |
| Fee structures | `/finance/fees/` |
| Billing / invoices | `/finance/billing/`, `/finance/invoices/` |
| Payments / recording | `/finance/payments/`, `/finance/payments/new/` |
| Receipts / PDF | `/finance/receipts/`, `/finance/receipts/<receipt_uuid>/print.pdf` |
| Debt / collections | `/finance/debt/`, `/finance/collections/` |
| Arrangements / follow-ups | `/finance/arrangements/new/`, `/finance/follow-ups/new/` |
| Concessions, refunds, corrections | `/finance/controls/`, `/finance/controls/new/` |
| Control detail / decision | `/finance/controls/<request_uuid>/`, `/finance/controls/<request_uuid>/decide/` |
| Actual refund / closure or reversal | `/finance/controls/<request_uuid>/disburse/`, `/finance/controls/<request_uuid>/reverse/` |
| Cash-up / open session | `/finance/cash-up/`, `/finance/cash-up/new/` |
| Cash count / review | `/finance/cash-up/<session_uuid>/count/`, `/finance/cash-up/<submission_uuid>/review/` |
| Import directory / upload | `/finance/imports/`, `/finance/imports/new/` |
| Private source / review | `/finance/imports/<batch_uuid>/`, `/finance/imports/<batch_uuid>/review/` |
| Reconciliation / proposal | `/finance/reconciliation/`, `/finance/reconciliation/new/` |
| Match review | `/finance/reconciliation/<match_uuid>/review/` |
| Chart / ledger / audit | `/finance/accounts/`, `/finance/ledger/`, `/finance/audit/` |

Finance navigation uses registered Django names and the existing school components.
Existing platform navigation and separate authentication portals were preserved.

### Migration and verification commands

From `kuzenga/` (the directory containing `manage.py`), with the intended environment
selected, back up and verify the target database before the controlled migration step:

```powershell
python manage.py showmigrations finance
python manage.py migrate finance --plan
python manage.py migrate finance
python manage.py check
python manage.py makemigrations --check --dry-run
python -m compileall -q apps/finance
python -m ruff check apps/finance tests/test_finance_controls.py tests/test_finance_operations.py
python -m pytest tests/test_finance_foundation.py tests/test_finance_accounts.py tests/test_finance_workflows.py tests/test_finance_controls.py tests/test_finance_operations.py -q
```

The `migrate finance` command above is an operator step, not a claim that recovery ran it
against the working database. PostgreSQL migration/trigger compatibility, concurrent
idempotency/allocation/numbering, row locks and deadlock/retry behaviour remain untested.
Browser responsiveness/accessibility and PDF visual verification remain unexecuted.
No live gateway, actual fund movement, provider-delivered reminder or statutory accounting
certification is implemented. Existing role grants are retained; no automatic platform
superuser or guardian access was added. Large-volume dashboard profiling remains outstanding.

## Final hardening recovery and acceptance checkpoint (2026-11-12)

This section supersedes the earlier acceptance limitations where explicitly stated.
Recovered the existing implementation and uncommitted work after interruption; no module
was rebuilt and no historical migration or working financial record was reset. Inspection
covered root AGENTS.md, applicable global/module rules, Git status/diff, finance services,
models, views, templates, tests, migration files and the isolated test runners. The prior
document stopped before recording the final hardening work below.

### Recovered and completed hardening

- `AllocationRetraction` is an immutable compensating record with authoriser, effective
  date and mandatory reason. Only `finance.approve` can retract; invalid/already released
  allocations and closed-period dates are rejected. Original allocations and receipt issue
  snapshots remain intact. Invoice settlement is released to available payment credit;
  cash received and net student ledger balance do not change because allocation itself
  is not a second accounting posting. Historical invoice/debt views respect the retraction
  date. Allocation effective dates prevent later allocations appearing at the original
  payment date. Legacy null dates retain the original posting-date interpretation.
- Reallocation to another valid invoice uses the existing allocation service, preserving
  student/currency/control-account and refund-reservation checks. The original unique
  payment/invoice allocation pair remains reserved after retraction: allocating again to
  that same pair requires a corrected payment, rather than silently reviving the old row.
- `ReconciliationRelease` preserves an incorrect approved match and its independent
  correction reason. A different approver from the original proposer and reviewer must
  release it. A replacement then needs a new proposal and independent approval. Database
  guards enforce one active match per statement row/ledger line while retaining old matches.
- Payment-plan amendments require an independent `finance.approve` actor, explicitly
  supersede the current plan and preserve the previous schedule. Original plan creation
  remains authorised through existing `finance.fees` permissions.
- Payment credit displayed in the UI now subtracts refund reservations, matching the
  posting/allocation contract. Posted payments, journals and receipts remain immutable.
- Student statements now export CSV and branded PDF. `/finance/reports/` provides live
  payment history, cashier/method summaries, debt ageing, grade/class debt, general ledger,
  trial balance/period movement and financial audit history. Filters and rows retain
  currency boundaries; collection status is explicitly current, not a historical
  confirmation claim. Debt is as-of end date; start limits the invoice cohort.
- CSV formula-like text is escaped while signed Decimal values remain numeric. Exports
  are private/no-store and audited. Preview shows 100 rows; CSV is limited to 5,000 source
  records and PDF to 500 report rows. No silently truncated financial totals are exported.
- Shared Pillow rendering supplies school branding, references and page numbering for
  receipts, statements and reports. PDF financial rows use labelled fields to avoid
  ambiguous wrapped table columns. These remain raster PDFs, not tagged/accessibility-
  certified documents or statutory financial statements.

Existing amendment paths remain: nonoverlapping fee versions; approved invoice credit/
debit adjustments; payment reversal plus corrected payment; independent concession
reversal plus a new benefit reference; payment-plan supersession; reconciliation release
plus independent rematching. Retroactive overlapping fee supersession and full paid-invoice
cancellation/reallocation to the same payment/invoice pair remain unsupported.

### Files and migrations

Recovered additions: `apps/finance/reporting.py`, `report_views.py`,
`templates/finance/reports.html`, `tests/test_finance_acceptance.py`,
`tests/test_finance_postgresql.py`, `scripts/finance_browser_server.py` and
`scripts/check_finance_browser.mjs`. Existing finance models/workflows/forms/views/URLs,
PDF rendering, navigation, payment/statement/reconciliation templates and the plan-amendment
regression were extended. `scripts/check_local_postgres.py --finance-only` reuses existing
deployment rehearsal infrastructure; Windows initdb now uses a private generated password
file, removed after initialization. No production connection or deployment was performed.

New migrations 0014–0019: allocation retractions and guards; reconciliation release/history
cardinality and active-match guards; allocation effective date and validation guards.
They preserve existing records and are forward-only where guards are installed. Apply the
entire migration chain with financial writers stopped; do not serve writes between the
schema and guard steps. The working application SQLite DB still has only 0001–0005 applied;
0006–0019 remain an operator migration step after backup and target verification.

### Verification status at recovery

- Fresh recovery: Django system checks, migration consistency, compilation and Ruff pass.
  Focused acceptance/core workflow run: **14 passed**, two existing Django URLField warnings.
- Earlier focused new acceptance run: **6 passed**, including retraction/history/rollback,
  rematching, tenant/permission rejection, reports and PDF generation. Intermediate failures
  exposed an accounting-period field mismatch and an overly specific form-error assertion;
  both were corrected. Existing plan regression now uses an independent approver and passes.
- **PostgreSQL migrations executed:** all finance migrations through 0019 applied on a newly
  created local PostgreSQL **16.15** cluster, with TLS and no production data. Earlier
  initialization attempts failed (restricted-token errors and Windows `--pwfile=-`
  handling); correcting the password-file handling enabled the isolated rehearsal.
  The isolated finance suite subsequently passed **56 tests**, including committed,
  multi-connection duplicate payment confirmation, concurrent billing retries, competing
  invoice allocation capacity, idempotency, balanced journals and whole-operation rollback.
  The server stopped cleanly. This is evidence for the tested two-worker cases, not a
  high-volume stress, deadlock-retry or availability certification.
- Browser harness recovered with form selection fixed: the first attempt selected the
  shared header form and stopped before login. A fresh headless Edge run uses a new
  synthetic SQLite DB, separate browser profile and loopback-only WSGI app. Edge later
  interrupted that run with a browser-owned sync screen. The harness now defaults to
  **Chrome**, disables sync and times out individual CDP commands. A fresh Chrome run
  **passed** the actual forms/workflows listed below; no application permission was
  relaxed to accommodate the runner.
- Receipt, student statement and trial-balance PDFs were generated from synthetic test
  transactions. Their embedded page images and the final page of a three-page sample were
  visually inspected for identity, amounts/currency, references, branding and page breaks.
  Cross-tenant receipt/statement access is tested. New labelled-field output is generated
  by the latest acceptance run; large real-school logos/font variants remain owner UAT.

### Final executed results and sign-off

| Verification | Executed result |
| --- | --- |
| Django checks and migration consistency | Passed; no issues and no model drift |
| Python compilation, scoped Ruff and JavaScript syntax | Passed |
| Finance template compilation | All 33 templates compiled |
| SQLite finance + assessments/attendance/school-portal regression | **84 passed**, 1 PostgreSQL-only skip, 2 existing URLField warnings |
| PostgreSQL 16.15 fresh migrations | All finance migrations 0001–0019 applied successfully in isolated local TLS cluster |
| PostgreSQL finance suite including concurrency | **56 passed**, 2 existing URLField warnings; runner exited successfully and stopped server |
| Real Chrome workflow acceptance | Passed with newly generated synthetic SQLite data |
| Final PDF pagination regression after visual correction | **1 passed**, 2 existing warnings; checks/lint passed |

No tests remain failing in the executed final runs. The SQLite skip is not counted as a
pass: the same PostgreSQL-only concurrency test executed and passed in the separate
PostgreSQL run. The final PDF pagination change affects rendering only; its focused test
was rerun after the broader database suites, rather than claiming those suites reran.

Exact broader regression command:

```powershell
python -m pytest tests/test_finance_foundation.py tests/test_finance_accounts.py tests/test_finance_workflows.py tests/test_finance_controls.py tests/test_finance_operations.py tests/test_finance_acceptance.py tests/test_finance_postgresql.py tests/test_assessments.py tests/test_attendance_foundations.py tests/test_school_portal_integration.py -q
```

Chrome exercised fee creation, signed billing preview/post, USD 50 partial payment,
receipt pages, USD 100 final payment, statements at 100 then zero, cash-up submission and
supervisor review, concession approval, refund approval without disbursement followed by
separate actual disbursement recording, independent bank matching, opening-import approval,
payment reversal, cashier permission denial, debt/collection/report navigation and dashboard.
Statement/import request sources were synthetic fixtures; browser file-upload mechanics
and all malformed-input combinations were not exhaustively tested in this run. CSV upload
and invalid-source processing have Django integration coverage.

A separate read-only persisted-state check of that browser DB confirmed **9 balanced
journals**, main student USD debt 50 after reversal, second student USD credit 40 and ZiG
credit 10, independently reviewed expected/actual cash-up 155, one refund disbursement,
one active reconciliation and one opening entry. No real transaction was recorded.

Desktop (1440px) and narrow (390px) dashboard screenshots were captured and visually
inspected. Finance navigation wraps and the shared mobile menu remains present. This is
not an exhaustive keyboard, screen-reader or every-screen responsive certification.

Receipt, statement and trial-balance page images were visually inspected. The closing
statement record originally split across pages; `document_chunks` now keeps labelled
financial records together when they fit. A regression covers that boundary and regenerated
first/last page images were inspected. Amounts, currencies, references, student identity,
navy/gold branding and final-page balances are readable in the synthetic samples.
Oversized single records can still span pages; real-school logos/fonts and physical printing
need school UAT. Financial PDFs remain raster documents.

Git-ignored artifacts retained for review:

- `build/finance-acceptance/`: receipt/statement/trial PDFs and first/last PNGs,
  plus three-page pagination sample.
- `build/finance-browser-89319e1a8735/`: synthetic browser database and
  `dashboard-1440.png` / `dashboard-390.png`.
- `.deployment-tools/postgres-staging-4a60t5t_/` at repository root: stopped isolated
  PostgreSQL rehearsal cluster/test state. Its generated credentials remain private;
  never package this directory into a release.

**Sign-off: the implemented workflows have passed the executed acceptance checks and
are ready for owner-led staging acceptance. This is not unconditional production release
approval.** Before production: review and include the currently uncommitted finance files;
back up and verify restoration of the intended target; rehearse the full incremental
upgrade on a representative non-production copy; apply 0006–0019 with writers stopped;
approve school role delegation, source retention and operational monitoring; complete
real-brand/document/accessibility UAT and representative load/deadlock/retry testing.
No production deployment, live gateway or real fund transfer was performed. The unresolved
canonical-backend ADR remains unchanged.

Owner UAT checklist (use the exact URL table above): create/version a fee; preview and
retry billing; confirm partial/full payments; compare receipt, invoice and statement;
retract an allocation and check unchanged net ledger balance; request/approve a concession;
approve a refund and verify no disbursement until separately evidenced; count/review cash;
import a statement and approve an exact match; release/rematch it with a separate reviewer;
preview/approve opening balances in separate currencies; compare reports and dashboard;
repeat with denied role and different-school identities. Outstanding feature limits remain
same-pair allocation reuse, overlapping retroactive fee supersession, full paid-invoice
cancellation, external reminders/conversion and statutory reporting.

### Reproduction commands and new URLs

From the application directory containing `manage.py`:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py showmigrations finance
python -m pytest tests/test_finance_foundation.py tests/test_finance_accounts.py tests/test_finance_workflows.py tests/test_finance_controls.py tests/test_finance_operations.py tests/test_finance_acceptance.py tests/test_finance_postgresql.py -q
python scripts/check_local_postgres.py --finance-only
node scripts/check_finance_browser.mjs
```

The PostgreSQL runner needs portable PostgreSQL 16 under `.deployment-tools/pgsql16/pgsql/`
or the existing `postgresql-16.15.zip`, local OpenSSL and permission to start a loopback
server. It generates new credentials/cluster/database, runs migrations/tests and stops
that server in `finally`; retained local test state is Git-ignored. Concurrency tests
are opt-in through `KUZENGA_RUN_PG_ACCEPTANCE=1` and require Django's `test_` database.
They use committed fixtures and multiple connections; append-only guards are not disabled.
The browser runner needs Node with built-in WebSocket, Chrome (or `KUZENGA_BROWSER_PATH`)
and the existing Python test dependencies. Its app DB is always newly created under
ignored `build/finance-browser-*`; it never opens `db.sqlite3`.

New routes, prefixed locally with `http://127.0.0.1:8000`:

- `/finance/allocations/<allocation_uuid>/retract/`
- `/finance/reconciliation/<reconciled_entry_uuid>/release/`
- `/finance/reports/?kind=collections` (also `cashiers`, `methods`, `debt`, `cohorts`,
  `ledger`, `trial`, `audit`; add `format=csv` or `format=pdf`)
- `/finance/students/<account_uuid>/?currency=<currency_uuid>&format=pdf`
  (also `format=csv`; existing date/year/term filters apply)

All existing workflow URLs are retained in the table above. School `/login/` and platform
`/platform/login/` remain separate; no platform-superuser finance bypass was added.

## Rules consulted and pending decisions

Root AGENTS.md, rules README/global rules 00–10; finance, student, academics, tenant,
authentication, subscriptions, reporting and communication module rules; ADR-0001;
existing tenant/audit/access/permission/student/academic/frontend implementations and tests.
The owner explicitly authorised `apps.finance`; no functionality is duplicated in
`backend/`. Canonical backend ADR approval remains pending; no ADR is labelled accepted.
Retention periods, statutory reporting policy, cashier/accountant delegation, guardian
portal linkage and external notification/payment providers remain unimplemented decisions.
