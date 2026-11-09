# API rules

- Follow the established API style of the selected backend. The `backend/` foundation configures DRF; the existing `kuzenga/` application currently documents server-rendered Django/HTMX workflows. Do not create parallel API surfaces without an approved architecture decision.
- Use resource-oriented, consistently named routes and HTTP methods. Preserve established response formats and status semantics; document intentional compatibility changes.
- Validate requests with serializers or established form/domain validation. Return only fields the caller may see and scope querysets before retrieving records.
- Require explicit authentication and permissions for protected operations. Public endpoints must be intentionally public; health checks disclose only coarse service health.
- Use pagination for potentially large collections, bounded filters and search, and stable ordering. Avoid unbounded exports or nested expansions.
- Return consistent client-safe errors with suitable HTTP status codes. Do not expose stack traces, SQL, secrets, internal hostnames, or cross-tenant existence information.
- Treat retries and duplicate submissions deliberately. Use idempotency or conflict handling for operations where duplicate execution can cause harm.
- Version or coordinate breaking public API changes and document deprecation and compatibility expectations.
