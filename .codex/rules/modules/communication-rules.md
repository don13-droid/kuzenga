# Communication module rules

- **Purpose:** Communication is a planned domain; supported channels and use cases are pending specification.
- **Models/business logic/API:** Do not assume messaging, announcements, SMS, email, push, templates, or delivery guarantees.
- **Authentication/permissions:** Define senders, recipients, consent, and tenant administrators before implementation.
- **Tenant isolation:** Keep school communications, recipient lists, and delivery data scoped to the tenant; prevent cross-school recipient disclosure.
- **Validation/errors:** Specify recipient validation, content limits, retries, and provider failure behavior.
- **Audit/tests:** Define audit and delivery evidence; test authorization, tenant boundaries, idempotency, and failure handling.
- **Dependencies/integration:** Select providers and background processing only through approved decisions; protect provider credentials.
- **Pending specification:** Channels, consent, templates, retention, delivery guarantees, provider integrations, and audit requirements.
