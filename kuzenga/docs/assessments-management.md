# Module 11: Assessments, examinations and report cards

## Recovery checkpoint

The interrupted workspace contained existing `academics.AssessmentCategory` and
`academics.GradeBoundary` models and platform configuration forms/tests. No assessment
app, marks, publication workflow, examination calendar, or report-card implementation
was present. Existing attendance/frontend changes were retained. This implementation
adds `apps.assessments` inside the existing Django application; it does not add features
to the separate `backend/` project or change the proposed status of ADR-0001.

## Access and setup

The existing `assessments` subscription entitlement is required. Owners, administrators
and HODs can manage/review; teachers can manage only assessments covered by an active
subject/class teacher allocation for the term or academic year. Teachers cannot approve,
publish, configure grading or schedule examinations. Parents, students, bursars and other
staff have no results access. Self-service parent/student identity linkage is not assumed.
All routes use existing school login, tenant middleware and scoped managers.

1. Apply only the additive assessment migrations: `python manage.py migrate assessments`.
2. Configure school assessment categories and grade boundaries using the existing platform
   configuration or the new school configuration forms.
3. Create a result policy, academic term/class/subject, enrolments and teacher allocations.
4. Create assessments, save individual or bulk rows in the marks grid, submit, review,
   approve and publish. The grid saves drafts atomically; UUIDs are checked against
   enrolments effective on the assessment date. Duplicate student rows are rejected.

## Calculations and workflow

All calculations use Decimal and round half up to two decimals. Grade intervals are
inclusive at both ends; configure adjacent intervals at percentage precision, for example
0–49.99 and 50–100. Overlaps are rejected by the school form; approval also rejects
uncovered/ambiguous calculated results, including configurations made through older forms.
Labels and pass classifications are school-defined; no national grading scale is hardcoded.

Within each subject/component, assessment percentage is weighted by its positive relative
weight. Component averages are multiplied by the policy's continuous/examination weights,
which must total 100. Missing marks either block submission or explicitly count as zero,
according to the selected policy. Exempt marks never count as zero: they leave the
denominator. An entirely exempt component is excluded and remaining component weights
are renormalized. An absent required component produces an incomplete total. Mixed
policy snapshots also produce an incomplete total. Subject averages include only complete
subjects; optional rankings require every represented subject to be complete and use
competition ties (1, 1, 3) on rounded averages.

Workflow is draft → submitted → under_review → approved → published. Reviewers may
return submitted/reviewed/approved assessments to draft with mandatory feedback. Marks
are editable only in draft. Published records cannot be returned to draft or overwritten;
they store original student, class, subject, policy, marks, grade and teacher-comment values.
Post-publication corrections require an explicitly designed superseding-result workflow;
silently changing published history is intentionally unavailable. Domain actions and mark
before/after values are recorded through the existing append-only audit facility.

Examinations have start/end timestamps, room and an existing staff membership as
invigilator. Overlapping rooms (case insensitive), classes and invigilators are rejected;
back-to-back sessions are allowed. Scheduling requests lock the tenant row to serialise
concurrent reservations on PostgreSQL. SQLite does not establish production concurrency.

## URLs

All paths are relative to the running school application:

| Path | Purpose |
| --- | --- |
| `/assessments/` | Assessment directory |
| `/assessments/new/` | New assessment |
| `/assessments/policies/new/` | New weighting/missing-mark policy |
| `/assessments/configuration/categories/` | School assessment category form |
| `/assessments/configuration/grades/` | School grade boundary form |
| `/assessments/<assessment_uuid>/` | Marks grid and workflow |
| `/assessments/<assessment_uuid>/schedule/` | Examination schedule |
| `/assessments/<assessment_uuid>/export.csv` | Published CSV mark sheet |
| `/assessments/results/` | Published history |
| `/assessments/examinations/` | Examination timetable |
| `/assessments/analytics/` | Term/class/subject assessment analytics |
| `/assessments/students/<student_uuid>/` | Current/historical results |
| `/assessments/students/<student_uuid>/terms/<term_uuid>/report.pdf` | PDF report |
| `/assessments/students/<student_uuid>/terms/<term_uuid>/comment/` | Headmaster comment |

The student profile displays the latest ten authorised published results and links to full academic history. `/login/` and `/platform/login/` remain
separate. Browser exports are authorised identically to result views; CSV cells that could
be interpreted as spreadsheet formulas are escaped. PDF downloads are private/no-store.

## Presentation and current limits

School pages reuse the existing base layout, school headings/buttons and form fields.
The optional `design/references/school-admin-dashboard.png` was not found. PDF reports
use navy/gold, school name/logo, assessment details, grades, weighted subject percentages,
averages, teacher comments, recorded headmaster comments and submitted-register attendance
counts. They are generated without an additional service/package. Standard PDF Helvetica
supports Windows-1252 text; other scripts need a future embedded Unicode font. Headmaster
comments and attendance are current at download time, while assessment values are snapshots.

Analytics are published assessment observations grouped by term/class/subject, rather than
an assertion that assessment-level pass rates equal final subject pass rates. Student history
shows progress across periods. Policies/categories/boundaries can be added; comprehensive
configuration editing and archival screens, spreadsheet uploads, rich interactive trend charts are not included. Report PDFs are downloadable
and printable; automated visual/browser validation remains necessary before design sign-off.

## Rules and validation

Consulted root AGENTS.md; rules README and global rules 00–10; examinations, reporting,
academics, student, tenant, authentication and attendance module rules; ADR-0001; existing
models, migrations, access/audit helpers, frontend components and tenant configuration tests.
The owner's Module 11 prompt supplies the previously missing product scope. Canonical
backend approval remains pending; no consolidation or cross-project duplication occurs.

Focused checks: `python manage.py check`, `python manage.py makemigrations --check --dry-run`,
`python -m pytest tests/test_assessments.py tests/test_tenant_configuration.py tests/test_tenant_isolation.py tests/test_school_portal_integration.py -q`.

### Session verification (2026-11-10)

- `python manage.py check`: passed, no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `python -m ruff check apps/assessments tests/test_assessments.py`: passed.
- `python -m pytest tests/test_assessments.py tests/test_tenant_configuration.py tests/test_tenant_isolation.py tests/test_school_portal_integration.py tests/test_student_management.py tests/test_access_and_entitlements.py tests/test_attendance_foundations.py -q`: **82 passed**, two existing Django URLField default-scheme deprecation warnings.
- Reviewed `sqlmigrate assessments 0001` and `0002`; applied both with
  `python manage.py migrate assessments`. Changes concern only new assessment tables.
  SQLite rebuilds its new tables to add constraints; no existing domain tables are rewritten.
- Created `db.pre-module11.20261110211635.sqlite3` using SQLite's backup API before
  migration. Compared all rows in 40 pre-existing data tables after migration: unchanged.
  Django content types and permissions gained entries for the new models, as expected.
  `PRAGMA foreign_key_check` returned no violations.
- Existing pending attendance migration was left unapplied. No assessment fixture/demo
  records were inserted into the working database. Tests use the configured test database.

Changed files: new `apps/assessments/` models/services/forms/views/URLs/PDF implementation,
two migrations, nine `templates/assessments/` templates, `tests/test_assessments.py`, and
this document. Existing integration files receive narrow additions:
`config/settings/base.py`, `config/urls.py`, `apps/tenancy/permissions.py`,
`apps/tenancy/navigation.py`, `apps/students/views.py`, and `templates/students/detail.html`.
Unrelated attendance, frontend and concurrently changing deployment work was preserved.
