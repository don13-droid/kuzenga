# Kuzenga development rules

This directory is the central, human-maintained index for platform engineering rules. Read this file first, then read every applicable global rule and the module rule for the code in scope. Root `AGENTS.md` asks Codex to do this explicitly; do not assume these files are automatically loaded.

## Rule precedence

Apply rules in this order:

1. Explicit project-owner-approved architectural decisions (ADRs).
2. Global development and security rules.
3. Technology-specific rules.
4. Module-specific rules.
5. Individual task instructions.

Higher-priority security requirements cannot be waived by a lower-priority instruction. If requirements at the same precedence conflict, surface the conflict and request owner clarification. Do not silently resolve architectural conflicts or misrepresent a proposal as an approved decision.

## Global rules

- [00 Global rules](00-global-rules.md)
- [01 Architecture rules](01-architecture-rules.md)
- [02 Backend rules](02-backend-rules.md)
- [03 Frontend rules](03-frontend-rules.md)
- [04 Database rules](04-database-rules.md)
- [05 Security rules](05-security-rules.md)
- [06 API rules](06-api-rules.md)
- [07 Testing rules](07-testing-rules.md)
- [08 Git rules](08-git-rules.md)
- [09 CI/CD rules](09-ci-cd-rules.md)
- [10 Documentation rules](10-documentation-rules.md)

## Module rules

Read [the module index](modules/README.md) and the file(s) matching the affected module and its dependencies. Module documents describe guardrails, not unapproved product requirements.

## Current architecture status

The repository contains an existing Django/HTMX/Tailwind application under `kuzenga/` and a separate Django REST Framework foundation under `backend/`. Existing documentation describes each, but no owner-approved ADR selecting one canonical backend was found. Treat this as an unresolved architecture decision: preserve both as-is, do not build duplicate functionality, and request an owner decision before consolidation, migration, or cross-project duplication. The observed frontend pattern is Django templates with HTMX and Tailwind; no separate frontend application was found. Do not create one without an approved reason.

## Architecture decisions

ADRs live in [`docs/architecture/decisions/`](../../docs/architecture/decisions/README.md). Only mark a decision `Accepted` when owner approval is explicit and recorded. Until then use `Proposed` or `Pending owner decision` and continue to follow existing implementations without expanding the disputed architecture.
