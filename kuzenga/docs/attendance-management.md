# Module 09 Attendance Management — Phase 1 checkpoint

Status: **partial implementation, not production-ready**. This checkpoint adds
backward-compatible data foundations in the existing `apps.attendance` app.
The Module 09 request supplies the new feature scope; it does not resolve the
broader canonical-backend ADR or define school-specific attendance policy.

## Inspection

Read root AGENTS.md, rule index and global rules 00–10, plus attendance,
academics, student, authentication, tenant, reporting and frontend guardrails.
There is no separate staff module rule: staff identities are existing tenancy
Membership/User records. Inspected attendance models/migration/services/views/
URLs/templates, dated StudentEnrolment, academic years/terms/classes and teacher
allocations, role permissions, core audit logging and notification preferences.
No working notification delivery provider was found. Platform views are unchanged.
`design/references/school-admin-dashboard.png` is absent; existing school-facing
components are the design source for subsequent attendance pages.

## Existing behavior retained

- `/attendance/` (`attendance:today`): current-year class list.
- `/attendance/register/<class_id>/` (`attendance:register`): today's register.
- Existing student/session records, four statuses, submitted actor/time, tenant
  scoping, class/day and student/session uniqueness and submission auditing.
- No application migrations have been applied to the user's development database.
  Pytest applies migrations to its isolated test database.

## Added foundations

Migration: `apps/attendance/migrations/0002_attendance_foundations.py`.

- Optional student record placement, arrival time, minutes late and absence reason.
- Optional register term. Existing records remain unchanged; historical placement
  and term links are intentionally not guessed or backfilled.
- Separate StaffAttendance linked to Membership, with staff/day uniqueness,
  validated roles/status/times, reason/notes and recording actor.
- AttendancePolicy: one per school; percentage treatment and follow-up threshold
  start unconfigured. Excused may be excluded, counted absent or counted present;
  late treatment must also be explicitly selected. Notifications default off.
- AttendanceNotification: pending-only records, unique per attendance record and
  guardian. Existing student/guardian links supply recipients. No messages sent.

New service functions in attendance/services.py:

- `attendance_percentage`: configured-policy calculation; missing marks never
  become absences; unavailable policy/zero denominator returns None.
- `record_staff_attendance`: active school owner/admin plus attendance entitlement,
  tenant-resolved membership, transactional write and audited corrections requiring
  a reason. Teachers and platform superusers cannot use this service.
- `queue_absence_notifications`: confirmed submitted absences only, opt-in policy,
  administrator authorization, recipient contact availability and deduplication.

No new pages, forms, URLs or sidebar links are exposed at this checkpoint.
The foundation services are not wired into existing request handlers yet.

## Critical remaining work

1. Replace implicit-present register opening with unmarked roster/draft workflow.
2. Add student/day duplicate prevention after inspecting legacy duplicates; do not
   delete records to force a constraint. Add dated placement and academic-period
   validation with historical preservation tests.
3. Enforce assigned-class teacher access and explicit platform exclusion on all
   attendance HTTP paths. Existing HTTP paths have not yet been hardened here.
4. Implement draft/submitted/corrected states, controlled reopening, concurrency
   checks, student correction audit and draft/submission forms.
5. Add staff UI, settings UI, absence workflow and private validated documents.
6. Add dashboard, reports/CSV, class/student history, configurable follow-up and
   student-profile integration, with efficient tenant-scoped analytics.
7. Expose pending notifications/history safely; no provider delivery is configured.
8. Add complete workflow/permission/migration tests and browser/PostgreSQL checks.

Existing register opening still defaults records to Present. This known gap is
**not fixed** by the additive foundation and must be resolved before release.
Do not deploy this checkpoint as the completed Module 09.

## Verification

From `kuzenga/`:

```powershell
python -m pytest tests/test_attendance_foundations.py tests/test_mvp_workflows.py tests/test_tenant_isolation.py -q
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py sqlmigrate attendance 0002
```

26 tests passed (two existing Django deprecation warnings). Django check: no
issues. Migration drift check: no changes. Migration plan contains only attendance
0002. Ruff on attendance models/services and foundation tests passed.
SQLite migration SQL reviewed; additions may rebuild tables in SQLite, so back up
before applying to a real database. Existing rows are copied, not deleted.
PostgreSQL, production rollout and browser behavior have not been verified.
Tailwind rebuild is unnecessary for these Python/model-only additions.

Manual command after backup/review, from `kuzenga/`:

```powershell
python manage.py migrate attendance
```

Applying this migration does not activate the unfinished UI/workflow features.
Rolling it back would discard newly entered foundation data; preserve any such
data before rollback. No migration reset, flush, auth model change or platform
interface modification is part of this checkpoint.
