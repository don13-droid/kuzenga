# ADR-0002 proposal for GitHub review — Vercel Preview

- Status: Proposed
- Date: 2026-11-12
- Decision owner/approval: Elevon Digital project owner. Preview preparation requested. External rollout and production approval are pending.
- Related: [ADR-0001](0001-canonical-backend.md), [Preview runbook](../../../kuzenga/docs/vercel-preview.md).

## Context

GitHub main contains ADR-0001 and Phase 1 product consolidation. An earlier deployment ADR is referenced in local work but is absent from this GitHub snapshot. Reconcile that record with this proposal before treating either as approved.

## Decision proposed

Use the existing product in `kuzenga/` as the Vercel build root for a protected Preview. Use native Django WSGI and Vercel static delivery, isolated Neon PostgreSQL with a direct migration connection, and a private S3-compatible bucket per environment. Keep the existing code, data model and migration history in place. Git integration builds Preview branches after external setup. Stage production only after separate authorization, and require manual promotion.

## Alternatives

The repository root has two independent Django trees and no root manage.py. The `backend/` project supplies infrastructure examples and has no school workflows. Cloudflare proxying in front of Vercel adds a second edge layer. Use Cloudflare DNS and Vercel's CDN for the app.

## Consequences

Preview requires separate database credentials, bucket credentials and protected access. Hosting capacity and upload limits require smoke testing. A future production release needs a restore rehearsal, reviewed migration plan and exact staged build verification. Roll back application traffic independently of database state.
