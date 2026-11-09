# Tenant module rules

- **Purpose:** Resolve and enforce school/tenant context and tenant-scoped access. Existing `kuzenga/apps/tenancy` and `apps/core` provide the implementation to inspect.
- **Responsibilities:** Tenant context, memberships/roles, and access boundaries already present in the existing project. New responsibilities require specification.
- **Models and relationships:** Inspect existing Tenant, Membership, and tenant-scoped model definitions before changes. Do not duplicate tenant identity or ownership models.
- **Business logic and API:** Reuse existing tenancy services, middleware, permissions, and access helpers. New endpoints or workflows are pending specification.
- **Authentication/permissions:** Resolve tenant from trusted server-side membership/context. Fail closed when tenant context is absent or invalid. Enforce backend permissions for every read and write.
- **Isolation:** Existing documented convention uses a shared schema and `TenantScopedModel`: tenant-owned models extend it; school code uses its scoped manager, never `unscoped`. Preserve and test this behavior; platform-level bypasses must be narrow and authorized.
- **Validation/errors:** Reject invalid, inactive, or unauthorized tenant context without exposing another school's data or existence.
- **Audit/tests:** Audit tenant membership and privileged access changes as required by existing policy. Add cross-tenant positive and negative tests for affected paths.
- **Dependencies/integration:** Other modules consume explicit tenant context and scoped services. Avoid circular imports and ad hoc tenant filters.
- **Pending specification:** Tenant lifecycle, delegated administration, platform support access, retention, and any changes to isolation architecture require owner decisions.
