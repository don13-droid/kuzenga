# CI/CD rules

GitHub Actions is the proposed CI/CD platform, not an existing approved deployment system. Do not add workflows as part of governance documentation; workflow adoption and deployment targets require owner approval.

When approved, CI should run formatting/lint checks, automated tests, migration consistency checks, dependency/security scans, and Docker builds using least-privilege permissions. Pin third-party actions to reviewed immutable versions and avoid exposing secrets to untrusted pull-request code.

Deployment standards:

- Build once and promote the same immutable artifact through staging and production.
- Require passing checks and human approval for production. Keep deployment credentials in protected environment secrets.
- Run migrations as a controlled release step with reviewed, backward-compatible changes and explicit failure handling.
- Define health checks, observability, rollback triggers, and recovery steps before enabling automated production releases.
- Do not automatically roll back database changes unless the migration is explicitly safe to reverse. Prefer forward fixes for irreversible data changes.
- Document staging/production environments, approvals, and operational ownership in an approved deployment ADR before implementation.
