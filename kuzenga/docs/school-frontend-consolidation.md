# School frontend consolidation checkpoint

## Design dependency

The approved School Administrator Dashboard reference image was not found in the
project during the current task. Searches included hidden/ignored files, common
image formats and reference/mockup/dashboard filenames. The available raster
images are uploaded tenant logos and a staff photograph. No replacement design
has been inferred from those assets or from the separate platform dashboard.

Visual consolidation is pending the approved image or its exact local path. Do
not label the existing school shell approved or complete. The platform design,
login pages and authentication boundaries must remain separate.

## Confirmed findings

- School dashboard, student, admissions and academic pages extend
  `templates/base/base.html`. This is still a minimal legacy school layout: it has
  a text sidebar and content area, without the requested topbar, profile menu,
  icon system, gold active navigation or shared page headers/breadcrumbs.
- `templates/dashboard/index.html` is a small statistics grid. Its metrics are
  real tenant-scoped student and class counts. No financial/attendance/demo
  numbers have been substituted for unavailable data.
- Modules repeat card, table, filter, pagination and action markup. Form-field
  helpers were duplicated under students/admissions; academic forms included the
  admissions helper. They now delegate to `components/form_fields.html` while
  preserving existing field markup and styles.
- `static/css/layout.css` supplies sidebar geometry, avatar styling and a
  module-named `student-workspace` form style used across domains. Tailwind's
  `theme.extend` is empty; there is no consolidated named school design-token set.
- The platform shell is `templates/superuser/base.html` and has its own topbar,
  navigation and design. It has not been replaced or copied into school pages.
- Current school navigation entries resolve to registered routes. No broken or
  stale school-sidebar route was found. Routing is not the cause of the visual
  inconsistency: those routes render the legacy shared school shell.

## Routing and Admissions access diagnosis

| Purpose | Exact URL |
| --- | --- |
| School login | `/login/` |
| School dashboard | `/` |
| Student Management | `/students/` |
| Admissions dashboard | `/admissions/` |
| Applications | `/admissions/applications/` |
| Academic Management | `/academics/` |
| Platform login | `/platform/login/` |

School login redirects to `/`. The root view opens the school dashboard for a
school user with active tenant context, sends users without a school context to
school selection, and redirects platform superusers to the platform directory.

Admissions requires an authenticated non-platform user, active school membership,
`admissions.view` permission and the existing student entitlement. Owners and
administrators have the required role permissions. Platform superusers are
explicitly denied, including when they have a school membership.

A read-only examination of active stored sessions found both platform-superuser
sessions without active school context and a school-owner session with the correct
membership, entitlement and permission. No identity, credential or session key was
logged. This establishes a valid role/session explanation for Forbidden responses;
it does not identify which browser generated the reported response. A user in the
platform portal must sign out and use a school owner/administrator account at
`/login/` to perform school admissions. Permissions have not been weakened and no
accounts/memberships have been promoted or reassigned.

After applying the already-authorized pending academic migration with a SQLite
backup, read-only requests using the stored eligible school owner/administrator
returned HTTP 200 for `/`, `/students/`, `/admissions/` and `/academics/`. These
checks resolved tenant membership through the existing middleware without saving
new login sessions or changing account permissions.

## Verification and remaining work

The focused integration tests cover login/dashboard routing, registered sidebar
links, owner/administrator Admissions access, platform exclusion, real scoped
metrics and shared form rendering. Existing academic, admissions, student,
tenant-isolation and portal tests remain the regression checks.

Once the reference is supplied: implement the school shell and visual tokens,
then consolidate stat cards, tables, filters, buttons, badges, confirmations and
pagination across dashboard, students, admissions and academics. Preserve forms,
services, routes and permissions. Verify desktop/tablet/mobile sidebar and topbar
behaviour in a browser, along with keyboard focus and the platform interface.
No browser screenshot or approved-reference comparison has been performed.

Executed from `kuzenga/`:

```powershell
python -m pytest tests/test_school_portal_integration.py tests/test_academic_structure.py tests/test_admissions.py tests/test_student_management.py tests/test_entry_routing.py tests/test_media_and_navigation.py -q
python manage.py check
python manage.py makemigrations --check --dry-run
python -m ruff check .
```

Result: 108 passed, with existing Django URL-scheme deprecation warnings. Tailwind
compiled successfully using the existing local 3.4.17 compiler; its Browserslist
database emits an existing update notice. Real browser/responsive verification
and a comparison to the missing reference remain unperformed.

## School visual refresh (reference supplied)

The owner supplied the reference in the conversation; its stated repository path
is absent. The shared school shell and dashboard now apply navy/gold navigation,
a profile topbar, rounded cards, and scoped form/table styling. Existing backend
behavior and permission-filtered links are preserved. Only existing dashboard
metrics are rendered; reference-only financial/trend/event data is not invented.
No campus photograph or official logo asset was available.

Focused validation: 17 portal/navigation/routing tests passed. Browser comparison,
keyboard interaction and responsive visual verification remain pending. This is
a shared visual refresh; individual-page fidelity remains to be reviewed.

Consulted rules: index, globals 00–10, module index and module guardrails including
tenant, authentication, student, admissions, academics, attendance and reporting;
ADR-0001 (Proposed), and this consolidation checkpoint. Canonical backend approval
remains unresolved; no backend consolidation was attempted.

### Consistency follow-up

Replaced encoding-damaged decorative glyphs with a shared inline SVG icon
component. Consolidated school card, control, validation, disabled and focus
styles, improved small-screen grids, and removed decorative metric rings that
could imply unsupported percentage calculations. Preserved all existing form
names/actions, navigation routes, HTMX flows and permission conditions. Platform
styles remain outside the school-scoped additions. The school stylesheet is now
formatted for maintenance. No backend files were edited.

Browser verification remains unavailable: no browser tool or installed Python
Playwright package was found. Responsive CSS and rendered-route tests provide
partial coverage, not evidence of a completed browser/reference comparison.

### Reference design-system refinements

School-scoped CSS now uses shared spacing, border, muted-text, link and surface
tokens. Midnight navy navigation, metallic gold active states, the existing
Kuzenga SVG brand mark, serif hierarchy, rounded cards and refined controls follow
the supplied visual reference. Superseded metric-ring declarations were removed;
button hover rules now follow their base gradients to avoid cascade conflicts.
Platform styles and backend Python files were not changed. Attendance controls
received accessible names while retaining their submitted field names.

Checks during these refinements: portal/media tests 10 passed; portal tests 5
passed; workflow/portal tests 12 passed (existing Django warnings). A structural
CSS check confirmed balanced blocks and shared token declarations. Browser
visual, hover and responsive verification is still pending. Rules consulted:
globals 00-10, frontend rule 03, applicable module guardrails and ADR-0001.

### Responsive refinements

Added tablet-specific gutters and two-column filters, single-column mobile
filters, wrapping page actions and navigation, and stacked mobile attendance
controls. Attendance tables now have named, keyboard-focusable horizontal scroll
regions. Existing desktop sidebar and mobile horizontal navigation remain.
Only CSS and attendance templates changed; field names and workflows are intact.
Desktop/tablet/mobile browser verification remains pending.

### Reusable school base

`templates/base/base.html` remains the single school base, preserving its title
and content blocks. Its sidebar and topbar are now included from
`base/_school_sidebar.html` and `base/_school_topbar.html`. Includes inherit the
existing request context; navigation permissions, locked states, school switch,
CSRF-protected logout and profile data remain intact. The main skip-link target
is programmatically focusable. No Python or platform layout was changed.

### Shared top navigation

The school topbar now provides a dashboard shortcut, active school context,
existing profile identity and a native keyboard-operable account dropdown with
school switching and CSRF-protected sign-out. It wraps on small screens and uses
solid white surfaces. No search/notification endpoints or fictional data were
introduced. Templates and CSS only; browser interaction checks remain pending.

### Breadcrumbs and headings

The school base exposes a reusable breadcrumbs block and a semantic breadcrumb
component. Student, admissions, academic and attendance pages use existing parent
routes and live page labels. Shared staff pages supply breadcrumbs only when the
school base renders that block; the platform base is unchanged. Older module
pages now have document titles matching their existing single page heading.
No backend files or form contracts changed. Browser verification remains pending.
