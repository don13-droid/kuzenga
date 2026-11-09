# ADR-0001: Canonical Kuzenga Backend

- **Status:** PROPOSED
- **Date:** 2026-11-04
- **Decision owner/approval:** Project owner approval pending
- **Implementation authorization:** Project owner authorized Phase 1 consolidation into `kuzenga/`; this does not change the ADR status or approve later production/data-migration decisions.
- **Related:** [Comparative audit](../backend-comparative-audit.md), [canonical backend architecture](../canonical-backend-architecture.md), [consolidation plan](../backend-consolidation-plan.md)

## Context

The repository contains two independent Django projects:

- `kuzenga/` contains the existing modular product application: a custom global user model, tenant memberships/roles, permission and entitlement logic, business models/services, templates/HTMX/Tailwind frontend, migrations, and domain/security tests.
- `backend/` contains an infrastructure-only Django REST Framework foundation with environment-based/PostgreSQL settings, a DB-aware health endpoint, and Docker/Gunicorn patterns. It does not contain the existing user model, tenant controls, business models, UI integration, or product migration history.

Maintaining both as peer backends risks duplicate settings, schemas, identity and authorization. Selecting the empty foundation as canonical would require a broad product/schema/UI port. The comparative audit recommends keeping the project with existing behavior as the source of truth and selectively integrating infrastructure patterns from the foundation.

This decision affects application ownership, API placement, database configuration, migration governance, deployment, and future module work. Security and data continuity take priority over convenience.

## Decision

**Proposed decision for project-owner review:** designate `kuzenga/` as the single canonical Django modular monolith. Preserve its custom user model, tenancy and permission source, domain apps, migration graph, and Django template/HTMX/Tailwind integration.

Subject to separate implementation approval, integrate DRF into this same Django project as an additional API transport layer; adopt reviewed PostgreSQL, environment-based settings, Docker/Gunicorn, logging, Redis/Celery, and CI patterns without keeping a second writable backend. Use PostgreSQL as the sole production database. Keep Redis as infrastructure only, not a source of truth. Add Nginx only if the selected hosting environment requires a self-managed reverse proxy/static edge.

The ADR remains **PROPOSED** until the project owner explicitly approves it. This proposal does not authorize code changes, file moves/deletion, migration creation, data conversion, deployment, or removal of `backend/`.

## Alternatives considered

1. **Select `backend/` as canonical and port all product behavior into it.** This begins from a clean infrastructure project, but must migrate the custom user, tenancy/RBAC, business domains, frontend integration, and existing migration/data history. It has more transition risk and no current product functionality to preserve there.
2. **Keep both as separate active backends.** This avoids immediate consolidation but perpetuates duplicate configuration and leaves identity, database/schema ownership, API authorization, and deployment boundaries unresolved. Not recommended.
3. **Keep `kuzenga/` canonical and selectively integrate `backend/` infrastructure.** This preserves existing working behavior and applies infrastructure improvements inside one runtime. Recommended, subject to owner approval and phased PostgreSQL/security validation.

## Consequences

### Expected benefits if accepted

- One owner for authentication, tenant boundaries, domain models, migrations, runtime configuration, and API behavior.
- Existing UI and business workflows remain in place while DRF APIs can be introduced incrementally.
- Infrastructure improvements are reused without making the empty foundation a second source of product truth.
- Future development follows one app/dependency/test/deployment setup and reduces architecture drift.

### Costs and risks

- `kuzenga/` requires production-hardening work: PostgreSQL enforcement, settings/secrets checks, DRF deny-by-default authorization, tenant write-path hardening, audit coverage, asset serving, containerization, task operations, and CI.
- PostgreSQL migration must preserve the custom user identity, historical primary keys, tenant relationships, and app migration graph. SQLite tests do not prove PostgreSQL behavior.
- API session/CSRF/client authentication and versioning need explicit contracts. DRF must reuse domain services and tenant permissions rather than duplicate workflows.
- Redis/Celery and Nginx increase operational responsibilities and should be enabled only with owners, health checks, security, and backup/recovery arrangements.
- `backend/` remains present during transition. It must not receive product features or write to the same production data while consolidation is in flight.
- No module requirements are approved by this ADR for admissions, finance, examinations, communications, or reporting.

### Reversal and review

Before any production cutover, the owner must approve the data source, backup/restore rehearsal, migration plan, security acceptance gates, and deployment rollback. Rejection leaves both projects unchanged and requires revising the target/plan. A later decision to select `backend/` requires a new reviewed ADR or an explicit superseding decision; do not silently reverse canonical ownership.
