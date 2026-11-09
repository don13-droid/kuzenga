# Authentication module rules

- **Purpose:** Establish user identity and authenticated sessions; exact product scope beyond the existing implementation is pending specification.
- **Responsibilities:** Inspect `kuzenga/apps/accounts` and current Django auth configuration before changing identity behavior. Do not create a second user/session system.
- **Models/relationships:** Preserve the existing custom email-login User model and its relationships; changes to identity, email uniqueness, or tenant membership require migration/security review.
- **Business logic/API:** Use Django's approved auth mechanisms and existing login flows. New registration, recovery, SSO, token, or API-auth behavior is pending specification.
- **Authorization:** Authentication establishes identity only; permissions and tenant membership must be checked separately on every backend operation.
- **Tenant isolation:** Resolve memberships and active tenant server-side. A user may only access tenants for which authorization is verified.
- **Validation/errors:** Avoid account enumeration and disclose only safe authentication errors. Apply validation and abuse controls to sensitive flows.
- **Audit/tests:** Test login/session behavior, permission denials, tenant boundaries, and security-sensitive changes. Never use real credentials in tests.
- **Dependencies/integration:** Prefer built-in Django facilities already in use. New providers or token packages require security and architecture approval.
- **Pending specification:** Password policy beyond Django configuration, MFA, account recovery, identity federation, and API token lifecycle are not decided here.
