# Architecture rules

- Keep domain modules within the modular monolith and communicate through explicit interfaces. Avoid circular imports and hidden cross-module writes.
- A module owns its domain rules and data. Other modules use documented services or APIs rather than reaching into its internals.
- Keep one authoritative backend and frontend architecture. The repository currently has two Django projects (`backend/` and `kuzenga/`), and available docs do not resolve canonical backend authority. Preserve both; do not duplicate new features across them or consolidate them until the owner records a decision in an accepted ADR.
- The existing UI is documented as Django templates, HTMX, and Tailwind in `kuzenga/`. The separate `backend/` project is a DRF infrastructure foundation. Do not infer that either defines a complete replacement architecture.
- Changes to module boundaries, persistence ownership, deployment topology, framework choices, shared tenancy, or public interfaces require an ADR proposal and owner approval before implementation.
- Avoid introducing multiple settings systems, dependency manifests, databases, API clients, or service instances for the same application concern without an approved reason.
- Prefer dependency direction from presentation/transport toward application/domain behavior; domain logic must not depend on HTTP request objects or templates.
- Record integration contracts and migration/coexistence plans when modules or projects interact.
