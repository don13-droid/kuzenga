# Student module rules

- **Purpose:** Manage student records; detailed product scope and lifecycle are pending specification.
- **Existing implementation:** `kuzenga/apps/students` documents students, guardians, enrolment history, and admission numbers. Inspect its models/services before changes; do not duplicate them in another app/project.
- **Models/relationships:** Preserve tenant ownership and existing relationship semantics. New fields, retention, identity matching, and deletion behavior require product and data review.
- **Business logic/API:** Keep workflows in domain services and follow the existing server-rendered interface unless an API is approved. New workflows/endpoints are pending specification.
- **Authentication/permissions:** Enforce role and record-level permissions on the server.
- **Tenant isolation:** Scope all student, guardian, enrolment, list, search, export, and nested access to the authorized tenant.
- **Validation/errors:** Validate identifiers and relationship ownership; avoid leaking student existence across tenants.
- **Audit/tests:** Protect sensitive student data, audit material record changes as required, and test tenant isolation and authorization.
- **Dependencies/integration:** Coordinate academic, attendance, admission, and reporting integrations through explicit interfaces.
- **Pending specification:** Student lifecycle, transfer, archival, guardian access, and jurisdiction-specific data requirements.
