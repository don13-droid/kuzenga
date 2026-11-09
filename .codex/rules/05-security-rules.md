# Security rules

- Enforce security on the server. Tenant scoping, identity, role checks, permission checks, and record-level access must be validated for every request and background task.
- Deny access by default where access is not explicitly granted. Resolve the authenticated principal and active tenant from trusted server-side context; never trust a submitted tenant, role, owner, or permission as proof of access.
- No school may read or mutate another school's data. Tenant isolation must hold for list, detail, search, export, bulk, nested, async, and error paths. Platform-level access must be explicitly authorized, narrow, and audited.
- Use Django's password hashers and authentication/session mechanisms. Never store or log plaintext passwords, tokens, recovery codes, or session IDs. Apply throttling and abuse controls to sensitive authentication endpoints when designed.
- Preserve CSRF protection for cookie-authenticated browser requests. Use secure production cookies, HTTPS, correct trusted-host/origin configuration, and safe CORS policy; do not disable controls to make tests pass.
- Validate and normalize inputs server-side. Use ORM parameterization and safe template escaping; do not interpolate untrusted SQL, HTML, shell commands, paths, or URLs.
- Restrict uploads by size, type, content, and access policy; store untrusted uploads safely and prevent execution. Do not expose private files through guessable public paths.
- Keep secrets in approved environment/secret stores. Commit only clearly fake examples. Redact sensitive data in logs, errors, analytics, and test fixtures; collect only what the product needs.
- Record security-relevant actions with actor, tenant, action, target, time, and outcome where applicable, while minimizing personal data and preventing tampering. Never treat an audit log as authorization.
- Add negative authorization and cross-tenant tests for security-sensitive changes. A failing check is not justification to weaken the policy.
