# Module 08 academic structure: implementation checkpoint

This extends existing AcademicYear, Term, Grade, ClassGroup and Subject records.
It reuses Membership teaching roles, StudentEnrolment history, student services,
admissions conversion, shared tenant context and AuditEvent. No student, class or
subject identity has been duplicated. The school design remains legacy and awaits
the approved reference described in [the frontend checkpoint](school-frontend-consolidation.md).

## Routes

- `/academics/`: current year/term, counts, placements, capacity and activity.
- `/academics/years/`, `/academics/terms/`, `/academics/grades/`.
- `/academics/classes/` and `/academics/classes/<uuid>/` for roster/curriculum.
- `/academics/subjects/`, `/academics/offerings/`, `/academics/allocations/`.
- `/academics/<kind>/new/` and `/academics/<kind>/<uuid>/edit/`.
- `/academics/offerings/<uuid>/deactivate/` and allocation equivalent: POST only.
- `/academics/progression/`: initial placement, promotion, repetition and transfer.

Existing route names for overview/list/create remain. Owners and administrators
manage structures and progression; progression also requires `students.manage`.
Teachers/HODs use existing `academics.view` access and see their own subject
allocations. School operations explicitly reject platform superusers. Existing
authorized platform tenant configuration uses a verified platform service path;
it does not confer automatic school-portal access. Both login portals remain.

## Periods

Years retain planned/active/legacy-closed states and add completed/archived. A
tenant can have at most one active year and one current year, enforced by partial
unique constraints. Current planned years remain supported, as in existing
platform configuration. Switching active/current designation is transactional,
retains previous years and clears displaced current-term designations. Earlier
active years become completed. Designation changes are audited.

Year and term dates must be valid and non-overlapping within their scope. Terms
must fit within the parent year; only a term in the current available year can be
current. One current term per tenant is database-enforced. Existing term/calendar
records prevent shrinking their parent year beyond their dates. Services serialize
period writes with the tenant lock; cross-row date-overlap rules are enforced by
domain/model validation rather than PostgreSQL-only exclusion constraints.

## Classes, offerings and teachers

Classes retain year/grade/name identity, capacity and active state, and add an
optional code and class-teacher Membership. Nonblank codes are unique within a
tenant/year. Teaching assignments require an active teacher/HOD membership from
the same tenant and an active non-platform user. A class with placements or
curriculum records cannot change its grade/year. Lists/details show student
counts, capacity and utilisation; roster visibility requires `students.view`.

Subjects add description and active state, retaining tenant-unique codes.
SubjectOffering assigns a subject to a grade/year, optionally limited to one
class, with compulsory/elective and active flags. A grade-wide offering and an
overlapping class-specific offering cannot both be active for the same subject.

TeacherAllocation assigns a teacher to an applicable offering/class, either for
the whole year or a matching term. Duplicate and year/term-overlapping allocations
are rejected. Identity changes use deactivation plus replacement rather than
rewriting historical assignments. Deactivating an offering also deactivates its
allocations; deactivating a subject deactivates its offerings. Records are retained.
No timetable conflict detector is introduced.

## Placement integration

The existing student enrolment service now locks tenant/student/class and validates
the target year, grade, class and capacity. This applies to student registration,
class moves, admissions conversion and academic progression. A configured capacity
is enforced against peak active-student occupancy over the requested remainder of
the year, including future placements. Null capacity is unlimited; zero means no
places. Lowering capacity below recorded occupancy is rejected. Reactivation of a
suspended student cannot bypass capacity checks.

Progression handles up to 100 distinct students atomically. Promotion requires a
higher configured grade order in a later year; repetition retains the grade in a
later year. Transfers are within the active school; no cross-tenant copying occurs.
Initial placement requires no earlier placement history. Dated previous placements
are closed, bounded by their original year, and new records are added. Repeating
the same open placement does not create another row or progression event. Any
failure rolls back the whole batch. A reason and audit event record progression
without copying student names into audit data.

## Migration and verification

`academics.0004_curriculum_structure` adds the new fields, two curriculum/allocation
models and partial unique indexes. Constant-default column additions use explicit
SQL with matching Django state to avoid rebuilding existing SQLite tables. The
nullable teacher FK uses Django's standard AddField. Existing records and migration
history are preserved. Existing conflicting current/active designations must be
resolved by an owner before deploying the uniqueness constraints; the migration
does not choose records to remove or silently repair. Local inspection found no
such conflicts. PostgreSQL deployment/locking still requires verification.

The local forward migration was applied after a SQLite backup. Before/after
comparison preserved existing year, term, class, subject and placement values.
No migrations remain pending in the inspected local database.

The academic suite has 21 focused cases. A broader run of academic, student,
admissions, configuration, tenant isolation, migration, portal and image tests
passed 130 tests. Portal/form consolidation then passed 108 focused cases.
Django checks, migration consistency, Ruff and Tailwind build passed.

Relevant instructions: AGENTS.md; global rules 00–10; academics, student,
admissions, tenant and authentication module rules; the owner's Module 08 request.
The canonical-backend ADR remains proposed and no consolidation was attempted.
