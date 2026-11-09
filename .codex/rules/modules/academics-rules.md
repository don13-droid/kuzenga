# Academics module rules

- **Purpose:** Existing project includes academic years, terms, grades, classes, and subjects; further scope is pending specification.
- **Responsibilities/models:** Inspect `kuzenga/apps/academics` and its migrations. Preserve existing ownership and relationships; do not make a parallel academic catalog.
- **Business logic/API:** Use existing services/patterns where present. New scheduling, progression, grading, or API behavior is pending specification.
- **Authentication/permissions:** Enforce school roles and operation-specific permissions on the server.
- **Tenant isolation:** Scope academic structures and related queries to the active tenant.
- **Validation/errors:** Validate dates, references, and tenant consistency according to approved rules; do not invent academic policy.
- **Audit/tests:** Test constraints, permissions, and tenant isolation for changes.
- **Dependencies/integration:** Coordinate with student, attendance, examination, and reporting modules through explicit contracts.
- **Pending specification:** Academic calendars, promotion rules, grading scales, timetables, and other curriculum policy.
