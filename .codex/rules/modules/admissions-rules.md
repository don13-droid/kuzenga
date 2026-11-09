# Admissions module rules

- **Purpose:** Admissions is a planned domain; its product boundary and workflows are pending specification.
- **Responsibilities/models:** No admissions-specific contract is approved here. Inspect existing student/admission-number behavior before proposing a separate module or model.
- **Business logic/API:** Application stages, forms, decisions, offers, and endpoint design are pending specification; do not infer them from a module name.
- **Authentication/permissions:** Define authorized roles and record visibility in an approved specification before implementation.
- **Tenant isolation:** Any future school-owned applications and records must be scoped to the authorized tenant on the backend.
- **Validation/errors:** Define required evidence, duplicate handling, and safe errors in the module specification.
- **Audit/tests:** Specify decision history and audit needs; test authorization and tenant boundaries for approved workflows.
- **Dependencies/integration:** Clarify relationship to student records and academic placement before building integrations.
- **Pending specification:** All admissions-specific requirements, models, endpoints, audit events, and integrations.
