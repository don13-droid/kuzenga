# Reporting module rules

- **Purpose:** Reporting is a planned cross-domain capability; report catalog and product scope are pending specification.
- **Models/business logic/API:** Do not invent metrics, exports, dashboards, or data aggregation semantics. Name each report's source-of-truth and freshness when specified.
- **Authentication/permissions:** Apply permissions to both report definitions and underlying rows; exports require the same or stricter authorization as interactive views.
- **Tenant isolation:** Scope every query, background export, cache key, and generated file to the authorized tenant.
- **Validation/errors:** Bound filters and date ranges; handle stale or unavailable source data safely.
- **Audit/tests:** Audit sensitive exports where required; test tenant boundaries, row-level permissions, aggregation correctness, and large-result handling.
- **Dependencies/integration:** Read through module-owned interfaces or approved reporting projections; avoid cross-domain writes.
- **Pending specification:** Metrics, report definitions, refresh/freshness, export formats, retention, and scheduling.
