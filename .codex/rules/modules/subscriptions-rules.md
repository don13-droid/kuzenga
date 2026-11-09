# Subscriptions module rules

- **Purpose:** Existing `kuzenga/apps/tenancy` includes Module, Plan, Subscription, and Entitlement concepts; inspect it before changes. Product and billing scope beyond the current implementation is pending specification.
- **Models/business logic/API:** Preserve the existing source of truth. Do not add a parallel billing/subscription model or assume payment-provider behavior.
- **Authentication/permissions:** Restrict plan and subscription administration to approved roles and platform capabilities.
- **Tenant isolation:** Tenant subscriptions and entitlements must be resolved for the correct tenant and enforced server-side. Entitlements do not replace access control.
- **Validation/errors:** Validate entitlement state and transitions against approved rules; fail safely when entitlement data is missing or inconsistent.
- **Audit/tests:** Audit administrative plan/entitlement changes as required and test access denial, transition rules, and tenant isolation.
- **Dependencies/integration:** Other modules consume entitlement checks through an explicit existing interface; avoid hard-coded plan checks across modules.
- **Pending specification:** Billing lifecycle, trials, renewals, grace periods, payment processing, proration, and platform operations.
