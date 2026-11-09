# Module 06: Student management and shared UI fixes

This implementation extends `apps.students` and its existing admission sequence,
student, guardian, guardian-link and dated enrolment records. The Module 06 task
provides the product scope; no new application, identity model or billing policy
is introduced. Follow the global rules and student, tenant, authentication and
academics module rules in the repository's `.codex/rules/` index.

## Images and media delivery

`MEDIA_ROOT` remains the existing `kuzenga/media/` directory and `MEDIA_URL` remains
`/media/`. Existing uploaded filenames and references are preserved. The previous
URL configuration had no route for these URLs, and tenant directory/overview
templates did not render school logos. The authenticated `/media/<path>` route
now serves only images referenced by an authorized database record:

- Platform superusers can view tenant logos and staff profile photographs.
- School members can view their active school's logo. School user administrators
  can view photographs of users in their school; other users can view their own.
- Student images require the active tenant, the students entitlement and the
  `students.view` permission.

There is no generic file-serving fallback. Unknown paths, other schools' records
and missing files return 404. Responses use private/no-store caching and nosniff.
The shared avatar component renders initials when no file exists and retains that
placeholder if an image request fails. Staff directories/profiles, the tenant
directory/overview/configuration and school navigation use this component.

The same protected route works with development and production settings. Do not
add Django's blanket `static(MEDIA_URL, document_root=MEDIA_ROOT)` handler or serve
the entire media directory directly through a public web server. Route `/media/`
requests through Django. Production still needs persistent media storage and an
operational backup policy; this change does not configure hosting.

## Shared navigation

Both base layouts load `static/css/layout.css`. Desktop sidebars have bounded
viewport heights, independent vertical scrolling and explicit content offsets.
Main content can scroll wide tables locally without widening the document.
Platform navigation wraps at narrow widths, and the topbar can wrap its controls.
Existing navy, gold, white and cool-grey styles and separate login portals remain.

## Student workflows

- `/students/` searches full names and admission numbers and filters by status,
  current dated class membership and recorded academic-year membership. Results
  use stable ordering and 25-row pagination; pagination preserves filters. Invalid
  or foreign-tenant filter values show errors and no results.
- `/students/new/` accepts an optional admission number; leaving it blank uses the
  existing tenant/year sequence. Generated numbers skip manually assigned numbers.
  The existing tenant/admission-number database uniqueness constraint is preserved.
  Registration can include a class, validated photograph and new or existing
  guardian. Database writes complete together or roll back together.
- `/students/<uuid>/edit/` updates personal details and the optional photograph.
  Admission identity is preserved. Dates of birth cannot be in the future, and
  the existing same-name/birth-date duplicate check excludes the edited student.
- Profiles show personal details, dated class/stream history, guardian contacts,
  status and paginated audit activity. Managers can assign classes, add/reuse
  guardians, update status and manage document uploads.
- Guardian links retain relationship, primary-contact and collection flags and
  add an emergency-contact flag. Primary/emergency contacts need a phone or email.
  Linking an existing guardian reuses its record; primary-contact changes only
  affect the selected student's links. Cross-tenant references are rejected.
- Class changes validate tenant ownership before modifying history. They close
  the previous open enrolment and add a new record. Reassigning the same open class
  is a no-op. Dates must follow existing enrolment boundaries; same-day or backdated
  moves that would overlap recorded history are rejected with a form error. The
  date-only history does not represent intraday moves.
- Transfer, withdrawal, graduation and archival close open enrolments on today's
  date. Suspension preserves enrolment dates; attendance already excludes inactive
  students. Reactivation keeps past records and allows a subsequent class assignment.
  Closing a record with a future open enrolment requires resolving its dates first.

Writes require `students.manage`; directory/profile access requires
`students.view`. Both require the active tenant and students entitlement on HTTP
requests. Domain services reject cross-tenant objects before writes and check
supplied actors' school management permission. Trusted internal callers may use
the existing `actor=None` convention only within explicit `tenant_context`.

## Private student documents

`StudentDocument` extends `TenantScopedModel`. Its files use
`PRIVATE_MEDIA_ROOT`, defaulting to `kuzenga/private-media/`, outside `MEDIA_ROOT`.
This directory is ignored by Git. Files use generated names rather than uploaded
names. The storage intentionally has no public URL.

PDF documents must be non-empty, have a PDF header/end marker and be at most 10 MB.
JPEG, PNG and WebP documents reuse the existing image validation (including a 5 MB
image limit and 20-megapixel limit). Filename extensions must match supported image
formats. These are format/size checks, not malware scanning or a PDF parser.

Only users with `students.manage` can upload or download documents. The download
route `/students/<student_uuid>/documents/<document_uuid>/` scopes both identifiers
to the active tenant. Downloads are attachments with an octet-stream content type,
nosniff and private/no-store caching. Viewing a document record does not disclose a
filesystem path or storage URL. No document deletion, retention or purge workflow
is introduced; existing records and files are retained.

## Audit and migration

The existing audit service records creation, personal-record edits, enrolment,
guardian links, status changes, document uploads and document downloads. Personal
edit values are redacted; document content, original filenames and guardian contact
values are not copied into audit metadata. Status history records before/after
status plus the operator's reason; the form asks operators to avoid unnecessary
personal information. The profile feed filters events to the active tenant and
selected student.

Run `python manage.py migrate` through the project's normal migration process.
`students.0002_student_management` adds the optional student photograph,
`StudentGuardian.is_emergency` (default false) and the document model. Existing
admission constraints and migration history remain. No data migration, deletion or
field renaming occurs. Tests apply the migration on a temporary SQLite database.
Explicit additive SQL (with matching Django migration state) avoids Django 5.2's
SQLite table rebuild for non-null `AddField` operations. Both columns retain
database defaults and supply empty/false values for pre-existing rows. The SQL
uses types and syntax supported by SQLite and PostgreSQL; rollback column removal
requires SQLite 3.35+ or PostgreSQL and must not be used after storing real uploads.
PostgreSQL deployment and backup/restore still require operational verification.
Reversing this migration after uploads would drop new database fields/tables and
lose their references: use a reviewed forward fix instead of resetting migrations.

## Manual browser verification

Verify platform and school layouts at narrow/mobile, tablet and desktop widths,
including a short viewport, long school/user names and wide directory tables.
Check sidebar scrolling, keyboard focus, topbar alignment, logo/photo fallback,
multipart registration/editing, validation errors and attachment downloads under
the real deployment's proxy/static configuration. Browser screenshots and visual
interaction are not covered by the Django response-rendering tests.
