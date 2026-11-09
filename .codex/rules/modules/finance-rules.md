# Finance module rules

- **Purpose:** Finance is a planned domain; product responsibilities are pending specification.
- **Models/business logic/API:** Do not create fee, invoice, payment, ledger, refund, or endpoint behavior based on assumptions. Define accounting and lifecycle requirements first.
- **Authentication/permissions:** Approved finance roles, separation of duties, and access scope must be specified before implementation.
- **Tenant isolation:** All future school finance data must be tenant-scoped; any platform operations require narrowly defined authorization.
- **Validation/errors:** Define currency, precision, rounding, reconciliation, and idempotency requirements in an approved specification.
- **Audit/tests:** Specify financial audit trail and retention; test authorization, tenant isolation, transaction integrity, duplicate processing, and calculations.
- **Dependencies/integration:** Clarify subscription, payment-provider, student, and reporting boundaries before integration. External payment services require security review.
- **Pending specification:** All models, workflows, payment integrations, accounting rules, permissions, audit events, and reports.
