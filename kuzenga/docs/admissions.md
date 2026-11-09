# Module 07: Student admissions and enrolment

This module implements the project owner's Module 07 task in `apps.admissions`.
It uses the existing Django school layout, `TenantScopedModel`, role registry,
student entitlement, academic structures, student services, private document
storage and `AuditEvent`. It adds no second student or guardian identity model,
public application portal, email delivery or billing integration.

## Routes and school access

| Page | URL |
| --- | --- |
| Dashboard | `/admissions/` |
| Application directory | `/admissions/applications/` |
| New application | `/admissions/applications/new/` |
| Application details, review and documents | `/admissions/applications/<uuid>/` |
| Edit application | `/admissions/applications/<uuid>/edit/` |
| Enrolment confirmation | `/admissions/applications/<uuid>/enrol/` |
| Authorized attachment download | `/admissions/applications/<uuid>/documents/<document_uuid>/` |

School owners and administrators receive `admissions.view`, `admissions.manage`,
`admissions.review` and `admissions.enrol`. Enrolment also requires
`students.manage`. Existing teacher, HOD, bursar, staff, guardian and student roles
have no admissions permissions. Platform superusers are explicitly rejected even
when they have a school membership. `/platform/login/` and `/login/` are unchanged.

All school requests require an active tenant membership and the existing
`students` entitlement; this is an integrated student workflow, not a new paid
entitlement. Domain services repeat authorization and tenant checks, including
when invoked outside HTTP. Admission writes require a named active school actor;
there is no `actor=None` bypass. Every tenant-related selection uses scoped
querysets and ownership validation. The directory's 25-row pagination preserves
filters. Invalid or foreign-tenant filters show errors and no results.

## Intake and application records

`StudentApplication` stores applicant names, optional preferred name, date of
birth and gender, intended year/grade/class, previous school, application date,
one primary guardian/contact snapshot and an optional link to an existing
`Guardian`. Application references use a generated `ADM-…` identifier with a
tenant/reference database uniqueness constraint. Student admission numbers are
assigned only during enrolment, by the existing student mechanism.

Drafts require applicant names but may omit guardian and placement details.
Application date defaults to today. Future application/birth dates are rejected.
Selecting an intended class can supply its year and grade; explicit mismatches
are rejected. Submission requires an available year/grade or class and guardian
names plus a phone number or email. No document category is mandatory because the
task did not specify school-specific evidence requirements.

Staff can select an existing school guardian rather than re-entering contact
details. The application stores a contact snapshot for review, while enrolment
reuses the selected guardian record. New contacts create a guardian through
student services during conversion. No fuzzy matching or automatic identity merge
is performed; additional student guardians can be added through Student Management.

## Controlled decisions and history

| Current status | Allowed next status |
| --- | --- |
| Draft | Submitted |
| Submitted | Under review |
| Under review | Accepted, Rejected, Waitlisted |
| Waitlisted | Under review, Accepted |
| Accepted | Enrolled, through conversion only |
| Rejected, Enrolled | No further transitions |

Acceptance, rejection, waitlisting and movement out of the waitlist require a
reason. Submitted, under-review and waitlisted application edits require a reason;
draft edits do not. Accepted, rejected and enrolled applicant details and documents
are read-only. This prevents silent changes to decided applications. Further
correction/reopening policies are not introduced by this task. Review notes may
still be appended, with a 4,000-character limit.

Decisions, creation, submission, significant edits, notes, document access and
enrolment use the existing `AuditEvent` service. Decision events preserve actor,
tenant, timestamp and before/after status. Personal edit values are redacted.
Private note/reason text is stored in `ApplicationNote`, linked one-to-one to its
audit event, rather than copied into audit metadata. The event remains the source
of actor/time/decision history; notes do not form a parallel audit system. Notes
reject ordinary instance/queryset edits and deletion. These are application-level
protections, not database-level tamper-proofing. History is tenant-scoped and
paginated at 20 events per page.

Version checks reject stale edit/decision forms. Evidence uploads and review-note
additions update the application's version so a reviewer must reload after new
information. Repeating a completed enrolment returns the linked student without
creating another student, guardian, class enrolment or conversion event.

## Transactional enrolment

Only an accepted application can be converted. The service locks the tenant and
application in that order, checks the selected class against the accepted
year/grade and any specifically requested class, and validates the effective date
against the intended year. By default, enrolment starts today or on the year's
start, whichever is later. Closed years and unavailable grades/classes are rejected.

Conversion calls the existing `students.services.create_student`,
`enrol_student` and guardian workflow. A provided admission number is validated
against existing tenant uniqueness; a blank one uses the existing generator.
The existing same-name/birth-date duplicate guard is applied when a birth date is
available. Resolving an existing student is an operator task; records are not
automatically merged. The application/student one-to-one link and status/link
check constraint protect conversion integrity.

Supporting documents are linked into the existing `StudentDocument` model using
the student upload service and the same committed private file references. Files
are neither moved nor copied, and original application documents remain available.
A missing or invalid stored document aborts conversion with a safe error. Student,
guardian, enrolment, sequence, link and audit writes share one transaction: failure
rolls them all back. PostgreSQL row locking provides serialization; SQLite's normal
write-contention limitations still apply.

## Documents and storage

`ApplicationDocument` classifies birth certificates, previous school records,
transfer letters and other evidence. It reuses `StudentDocumentStorage` and
`validate_student_document`, including private storage outside `MEDIA_ROOT`,
generated filenames, PDF signature/end-marker checks (10 MB), and validated
JPEG/PNG/WebP images (5 MB, up to 20 megapixels). These checks do not constitute
malware scanning or a complete PDF parser.

Downloads require `admissions.view`, the active tenant and student entitlement.
Both application and document identifiers are checked. Responses are attachments
with an octet-stream content type, nosniff and private/no-store caching. Private
storage has no public file URLs; `/media/` does not serve admission documents.
There is no document deletion or replacement workflow. Keep the private storage
directory persistent and outside public web-server/static mappings.

## Files, migration and checks

Implementation lives in `apps/admissions/{models,services,access,forms,views,urls}.py`
and `templates/admissions/`. Integration changes are limited to installed apps,
project URLs, school navigation, permission definitions and role labels. Student
and academic production models/services are reused without modification.
The student migration test restores all dependent app migrations, including
admissions, after testing historical student data.

`admissions.0001_initial` creates only the three admissions tables, their foreign
keys, indexes and constraints. Constraints are included in the initial table
definition to avoid SQLite table remakes. Existing student/guardian/academic data
and migrations are unchanged. Use `python manage.py migrate` in the normal release
process. Do not reverse the admissions migration after recording real applications;
that would remove the new tables. Use backups and reviewed forward fixes.

Focused tests are in `tests/test_admissions.py`, alongside the existing student,
tenant-isolation, access, portal-routing and student-migration tests. Run Django
`check`, `makemigrations --check --dry-run` and Ruff. Tailwind should be rebuilt
when template utility classes change. The tests use temporary SQLite databases;
PostgreSQL execution, concurrent conversion under PostgreSQL and browser layout/
interaction behind the deployment proxy still require verification.

Validation executed from `kuzenga/`:

```powershell
python -m pytest tests/test_admissions.py tests/test_student_management.py tests/test_mvp_workflows.py tests/test_tenant_isolation.py tests/test_tenant_user_admin.py tests/test_access_and_entitlements.py tests/test_entry_routing.py tests/test_student_migration.py -q
python manage.py check
python manage.py makemigrations --check --dry-run
python -m ruff check .
git diff --check
python manage.py sqlmigrate admissions 0001
```

The focused test run passed 118 tests, including 44 admissions cases. System,
migration consistency, lint and whitespace checks passed. Reviewed SQLite SQL
creates only admissions tables and indexes. Existing Django URL-scheme
deprecation warnings remain. Tailwind was rebuilt with the locally installed
3.4.17 compiler; its existing Browserslist database reports an update notice.

Consulted rules: global rules 00–10 and admissions, student, academics, tenant and
authentication module rules. The owner's task supplies the admissions product
scope that the admissions guardrail file previously marked pending. It does not
resolve the proposed canonical-backend ADR or authorize backend consolidation.
