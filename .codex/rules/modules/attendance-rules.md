# Attendance module rules

- **Purpose:** Existing project documents daily class registers with open-to-submit workflow; additional policy is pending specification.
- **Responsibilities/models:** Inspect `kuzenga/apps/attendance`, services, and migrations before changing register behavior.
- **Business logic/API:** Reuse domain services. New corrections, attendance codes, notifications, or API contracts require specification.
- **Authentication/permissions:** Restrict register creation, submission, correction, and viewing according to approved roles.
- **Tenant isolation:** Scope registers, students, classes, and reports to the active tenant; verify all linked records belong to that tenant.
- **Validation/errors:** Preserve existing workflow invariants and return safe errors for invalid state transitions.
- **Audit/tests:** Test state transitions, duplicate handling, permissions, tenant isolation, and auditability of approved corrections.
- **Dependencies/integration:** Use approved academic class and student interfaces; avoid cross-module direct writes.
- **Pending specification:** Attendance codes, late/absence policy, correction windows, notifications, exports, and statutory reporting.
