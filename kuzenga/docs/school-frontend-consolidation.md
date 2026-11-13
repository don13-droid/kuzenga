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

### Shared responsive content container

The school base now wraps messages, breadcrumbs and page content in
`.school-page-container`: full available width up to 1600px, centered, with
shrinkable children. Existing school gutters remain 32px on wide desktops,
28px normally, 20px on tablets and 16px on mobile. Narrow form-specific maximum
widths are preserved. The topbar remains outside this content width constraint.
No routes, form fields, backend or platform markup changed. Browser verification
at desktop/tablet/mobile widths remains pending.

### Consistent navigation states

Shared sidebar links now distinguish exact current pages (`aria-current=page`)
from ancestor sections (`aria-current=location`), retaining gold styling through
detail and edit screens. Parent and child entries can both indicate location.
Academic and admissions subnavigation now share pill spacing, hover states and
exact current-page styling. Existing URL generation, permissions and locked
module access remain unchanged. Templates/CSS only; browser verification pending.

### Mobile sidebar toggle

The shared topbar exposes a Menu button below 768px. A deferred school-only
script controls the sidebar's hidden state and aria-expanded value, closes it on
Escape or navigation, returns focus to the toggle and restores desktop navigation
when crossing the breakpoint. Without JavaScript the sidebar remains visible.
No backend or platform changes. JavaScript syntax checked with `node --check
kuzenga/static/js/school-layout.js`; browser interaction testing remains pending.

### Scrollable small-screen navigation

The expanded mobile sidebar now uses a vertical navigation list bounded to 55%
of viewport height (with vh fallback), independent vertical scrolling, stable
scrollbar space and contained scroll gestures. The nav is keyboard-focusable
with visible focus, and chevrons remain visible. Desktop retains its scrollable
full-height sidebar. Existing links, toggle and access conditions are unchanged.
Checked CSS breakpoint/overflow declarations; browser scrolling verification is
still pending.

### School-wide inheritance audit

Audited 29 school/client full-page templates: all extend `base/base.html` or the
existing portal-selected `base_template`. School login, selection, access states,
activation and password reset are included. Shared staff templates retain platform
inheritance when used by platform views. Student enrolment/guardian forms and the
complete form helper now reuse `components/form_fields.html`; the school student
save button no longer references a platform-specific class. Field names, actions,
prefixes, CSRF and server validation are preserved. School-wide control widths
and border tokens also apply to legacy account forms. No Python changed.
Consulted global rules 00-10, frontend rule 03, tenant/authentication/student and
adjacent module rules, and ADR-0001. Visual browser verification remains pending.

### Dashboard module refinement

Reformatted the school dashboard into readable semantic sections with the
reference's welcome hierarchy, live metric cards and navy quick-action panel.
Class counts use a class icon. School Overview displays existing school metadata
and the current membership role rather than repeating totals or inventing
performance percentages. Quick actions retain permission-filtered routes and
explicit plan labels. No new queries, Python changes, mock data or photo assets.
Browser/reference fidelity verification remains pending.

### Student Management refinement

Directory, create/edit and profile templates now use shared heading, description,
status and form-action styles. Directory scrolling is named and keyboard
accessible; status pills preserve the original status labels. Profile identity
and edit action share one responsive header. Save/cancel actions retain existing
routes, and guardian, placement, status, document and history markup keeps its
original fields and permission conditions. Replaced literal question-mark
separators in the profile. No Python or HTMX response contracts changed.
Browser/reference comparison remains pending.

### Admissions & Enrolment refinement

Dashboard, directory, create/edit and enrolment confirmation use a reusable page
heading component. Application details use the shared responsive action header;
status labels use shared neutral badges, and the directory has a named keyboard
scroll region. Form action bars preserve save-draft and submit button semantics,
with existing-route cancel links. Review transitions, reasons, concurrency values,
uploads, enrolment, pagination and permission conditions remain unchanged.
Templates only; browser/reference comparison remains pending.

### Academic Management refinement

Overview, create/edit, progression and class detail pages reuse the shared page
heading component. Directories use consistent action headers and named,
keyboard-focusable scroll regions. Save/progression actions share the form action
bar and existing-route cancel links. Corrected literal question-mark separators
and missing-value display text. Preserved academic fields, concurrency values,
filters, pagination, deactivation actions, placement modes and permission checks.
No Python changed. Browser/reference comparison remains pending.

### Teachers and Staff refinement

Existing Users & Staff pages retain the shared portal-selected base. School
headers and neutral status badges follow the school design system, while platform
header classes remain conditional. Directory role/status selects now have
accessible names; table scrolling and pagination have labels. Profile, form and
role cards inherit the existing shared school styles. No teacher/staff domain
features were added, and primary-owner/shared-identity protections, activation,
reset, role and status actions are unchanged. Templates only; browser comparison
remains pending.

### Attendance refinement

Daily class list and register now reuse shared headings, status badges and form
actions. Tables have explicit column headings and correct empty-state spans,
retaining named scroll regions. Register submission retains its exact field
names, configured status choices, CSRF and open/submitted conditions. Added the
existing attendance-list route as a return action. Templates only; backend and
register services unchanged. Browser/reference comparison remains pending.

### School administration refinement

School selection uses the shared heading component and selectable card treatment;
roles/permissions carries a school administration heading without changing the
platform variant. Selection, locked-module and forbidden pages now have explicit
document titles and inherit the same school surfaces and typography. Existing
school user administration remains intact. General school configuration/settings
routes are currently platform-only; no school configuration route or permission
was introduced. Templates/CSS only; browser comparison remains pending.

### Remaining school-facing account and access pages

School sign-in, activation and password reset now use the reusable school heading
component and accessible error announcements. Sign-in controls include standard
autocomplete attributes. Account completion announces its result; access panels
have consistent centering and an existing dashboard return link. All retain the
school base, original fields, CSRF, validation and token workflows. Platform login
is unchanged. No Python changes. Finance and Reports have no implemented school
pages and were not invented. Browser/reference comparison remains pending.

### Reusable dashboard KPI cards

`components/school_kpi_card.html` standardizes the dashboard card shell, label,
value and existing SVG icon. Callers pass explicit context with `only`; no data
fetching, invented metrics or fallback numbers are added. Dashboard continues to
iterate the original server-provided `stats`, preserving zero values and empty
states. Existing shared metric styles provide responsive sizing and typography.
No backend changes; browser comparison remains pending.

### Reusable data-table pattern

Five school tables now extend `components/school_table.html` through module-owned
partials. The shared component owns the named keyboard-scroll region, border,
radius and shadow; each module retains its exact table columns, rows, actions and
empty text. Student `rows` target and rows-only HTMX response are intact. Staff
directory adopts the same container style only in school context, retaining its
platform layout. Shared CSS standardizes headings, cells and empty-state padding.
No Python changes; browser verification remains pending.

### Reusable search/filter bars

Student, admissions and academic directories now include
`components/school_filter_bar.html`, which reuses existing field rendering and
GET submission with caller-supplied clear URL/button text. All query field names,
choices, initial values, errors and hidden inputs remain server-rendered.
Two-column fields collapse to one on mobile, with a consistent action row.
Staff filters retain their shared manual fields and platform behavior, adopting
the school filter surface in school context. Pagination queries are unchanged.
Templates/CSS only; browser verification remains pending.

### Primary and secondary buttons

Added explicit school button variants: metallic gold primary actions and white,
navy-text bordered secondary actions, with shared sizing, focus, hover and
disabled states. Existing school action elements retain their original element
types, names, values, URLs and permission conditions. Shared staff templates opt
in conditionally for school context. Filter and clear controls use the shared
variants. Backend unchanged; browser verification pending.

### Form inputs and validation errors

The shared field component now provides consistent labels, help text, field and
non-field error announcements, invalid borders and checkbox spacing. Widgets,
required/disabled attributes, values and hidden fields remain Django-rendered;
validation text is unchanged. Help-text IDs match Django's standard widget
references. Activation and password-reset pages reuse the same component.
School CSS defines consistent input sizing and validation states; no backend
validation or authentication behavior changed. Browser verification pending.

### Reusable status badges

`components/school_status_badge.html` now renders existing student, admissions,
attendance and school staff status labels through one shared pill style. Exact
labels and attendance not-started conditions are retained. Neutral navy/grey
styling avoids inventing status classifications or relying on color alone; long
labels wrap on small screens. Platform staff status rendering stays plain as
before. No status transitions, Python or permissions changed. Browser verification
remains pending.

### Reusable navigation tabs

Academic and admissions navigation now extend `components/school_tabs.html`.
Existing links, current-page attributes and permission conditions are retained.
The shared tab surface has consistent sizing, focus and horizontal scrolling on
small screens. These are page-navigation links, so native nav/link semantics are
preserved rather than adding ARIA tab roles for nonexistent in-page panels.
No backend or unfinished module links added. Browser verification pending.

### Reusable empty states

Existing literal loop-empty messages now use `school_empty_state.html` for
consistent muted text, spacing and responsive wrapping. Their original table
cells/colspans and list elements remain intact; no records, no filter matches and
no active modules retain distinct original wording. Staff directory adopts the
component only in school context. No invented records or automatic actions.
Templates/CSS only; browser verification pending.

### Reusable pagination

Student directory/activity, admissions directory/history, academic directory/class
roster and school staff directory use `school_pagination.html`. The component
accepts the existing page object, label, query and page parameter. Original
page/activity_page/history_page parameters and previous/next visibility remain;
filter strings stay escaped and pagination page sizes/order remain server-owned.
Staff platform pagination is retained verbatim. Styling uses existing secondary
buttons and wrapping spacing. No backend changes; browser verification pending.

### Loading indicators

The school base includes a reusable polite loading status with a restrained gold
spinner. Native form submissions show feedback after confirmation handlers accept
the event; controls remain enabled so submitter names/values are preserved. HTMX
requests use beforeRequest/afterRequest and failure/abort lifecycle events with
concurrent-request tracking. BFCache restoration clears stale feedback; native
navigation feedback also clears after 30 seconds. Reduced motion uses a static
indicator. No routes or HTMX swap behavior changed. `node --check` passed;
browser interaction verification remains pending.

### Success and error notifications

The school base now reuses `school_notifications.html`. Django message text is
preserved; standard numeric message levels determine restrained success, warning,
error and information treatment, so extra tags do not break severity styling.
Errors announce as alerts; other messages use status semantics. Failed school
HTMX requests display a safe static message without server response bodies or
automatic retries. No delivery/success is claimed for a failed request.
JavaScript syntax check passed. Backend/platform behavior unchanged; browser
interaction verification remains pending.

### Cross-module consistency pass

Reviewed existing school page headings, action variants, navigation, controls,
tables and feedback against shared components. Student forms now reuse the page
heading include; academic class/allocation states reuse status badges; cancel and
attendance return actions use secondary button styling. All 72 templates compile.
School modules retain one school base and scoped design tokens; platform templates
remain separate. This is implementation consistency evidence, not completed
browser/reference verification. Module 09 backend remains at its documented Phase 1
checkpoint and is not represented as a completed attendance feature set.
