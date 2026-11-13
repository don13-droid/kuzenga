# ADR-0002: Vercel deployment of the existing Django application

- Status: Accepted for preparatory implementation only
- Date: 2026-11-10
- Decision owner/approval: Project owner explicitly stated, "I approve ADR-0002 for preparatory implementation only" on 2026-11-10. This authorizes configuration, PostgreSQL integration, static assets, environment configuration, CI/CD preparation and testing; it excludes deployment, DNS changes, paid resources, production database modifications and merging to main without further explicit approval.
- Preparation authorization: Owner requested repository audit and safe deployment preparation using Vercel, Neon PostgreSQL, GitHub, Spaceship DNS and external object storage. Preview and production deployment each require separate approval.
- Phase 2 authorization (2026-11-11): Owner approved isolated development/staging integration and tests, including resolving upload compatibility with Cloudflare R2, Python 3.12 validation, empty staging database migrations and finance lint. Direct-upload preparation uses authenticated, short-lived PUT grants, private quarantine, checksum/content validation and the existing form/service commit paths. No production operation, deployment, DNS write, paid resource or merge is authorized.
- Related: [ADR-0001](0001-canonical-backend.md), [deployment audit and runbook](../../operations/vercel-deployment.md)

## Context

The product and CI use `kuzenga/`; `backend/` remains a separate infrastructure reference. ADR-0001 is proposed with recorded Phase 1 implementation authorization. This record does not promote ADR-0001 to Accepted. Local uploads and private document storage currently require durable disk. Existing Docker deployment is not a Vercel runtime configuration.

## Decision

Propose deploying the existing `kuzenga/manage.py` application through native Vercel Django support, with project root `kuzenga`, an explicit WSGI entrypoint, production settings, native static collection/CDN, Neon PostgreSQL and private S3-compatible media storage. Preserve authentication, tenant scope, templates, business services and migration history. Leave `backend/` unchanged.

Use isolated preview and production databases, credentials and storage. Use pooled runtime PostgreSQL connections with TLS; use a direct connection for a controlled, serialized migration release step. Never run migrations on requests or automatically on every preview build. Keep GitHub Actions checks and require review before production. Do not enable Git deployments until environment separation and approval controls are configured.

Do not select a background provider until a concrete workload and operating owner are approved. Do not change DNS or expose real school data before release gates pass.

Preparatory implementation is approved under the architecture and CI/CD rules. Spending, DNS writes, production database modification, merging to main and deployment remain unauthorized.

## Alternatives considered

1. Keep the container deployment model: supports persistent workers but needs a separately selected host and operational plan.
2. Native Vercel Django: matches the requested platform and preserves server-rendered UI; requires external persistence and verified runtime limits.
3. Legacy Vercel `/api` wrapper or a new frontend: unnecessary with native Django support and would add maintenance or application changes.

## Consequences

- Production cannot rely on local disk or process memory for durable state.
- Both ordinary image storage and the explicit private document backend must support object storage without public media URLs or changed authorization.
- Database rollback is independent of application rollback; preserve compatible migrations and use forward fixes when reversal would lose data.
- Owners must choose accounts, regions, bucket provider, retention, recovery objectives, alert ownership, approved recurring cost and domain.
- Vercel Git integration must not publish unapproved commits. Public production release requires verified backups, restore rehearsal, tenant isolation and live endpoint checks.
