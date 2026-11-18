# Kuzenga agent dispatcher — implementation contract

Status: design committed; no autonomous Codex runner is active yet.

## Operating model
User instruction → ChatGPT task specification → GitHub issue (`agent:ready` after triage) → authenticated dispatcher → supported Codex agent API/SDK or runner → feature branch/PR → CI → Vercel preview → human approval → production.

The dispatcher MUST NOT treat an issue being created as proof that Codex started. Record queued, claimed, running, blocked, PR-ready, approved, deployed, failed with timestamps and job IDs. Use idempotency keys, short-lived least-privilege credentials, signed webhooks, concurrency controls and full audit logs. Verify supported Codex programmatic execution before enabling dispatch.

## Approval policy
No approval for read-only inspection, draft PRs, isolated tests or previews. Explicit approval required for production deployment, destructive database migrations, DNS edits, branch deletion, financial actions, and external bulk messaging. No credentials in issues or logs. Never use production database for preview tests. Document rollback and backups.

## Branch preservation
On 2026-11-18 comparisons against `release/production-20261116`: `feat/finance-module`, `fix/mobile-access-production-prep-20261115`, `fix/preview-foundation-20261113`, `integration/local-github-20261115`, and `main` were behind with zero unique commits; `chore/vercel-preview-readiness` diverged with one unique commit. Preserve and review that commit before cleanup. Target permanent branches `main`, `develop`, `release` (exact release naming/branch protection to be decided). Do not delete branches until PR usage, deployments, local-only commits, and preservation are checked.

## First acceptance test
Create a harmless documentation-only issue; runner claims it, opens a PR on a temporary branch, CI runs, status and logs are posted, and no production mutation occurs. If any step is unsupported, mark blocked with concrete reason.

Related issue: #8.
