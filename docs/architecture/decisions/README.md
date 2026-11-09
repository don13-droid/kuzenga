# Architecture Decision Records

Use this directory for decisions that affect platform architecture, security boundaries, data ownership, public interfaces, dependencies, or operations. ADRs explain a decision; they do not grant approval by their existence.

## Status and approval

Use `Proposed` while under review, `Pending owner decision` when owner input is required, `Accepted` only after explicit project-owner approval is recorded, and `Superseded` or `Rejected` when applicable. Preserve the record and link any replacement. Do not infer approval from implementation, silence, or an AI-generated document.

## Naming and required sections

Name files `NNNN-short-title.md`, using the next available number. Each ADR must contain:

```markdown
# ADR-NNNN: Title

- Status: Proposed | Pending owner decision | Accepted | Rejected | Superseded
- Date: YYYY-MM-DD
- Decision owner/approval: name or role and evidence, or `Pending`

## Context
## Decision
## Alternatives considered
## Consequences
```

State constraints and affected modules. Include migration, security, operational, compatibility, and rollback consequences when relevant. Link related ADRs and specifications. Keep alternatives factual and note why they were accepted or rejected. Update the status only when the decision owner changes it.

## Current unresolved architecture question

No ADR selecting the canonical backend was found during establishment of this convention. The repository contains the existing Django/HTMX/Tailwind application at `kuzenga/` and the newer Django REST Framework foundation at `backend/`. Do not create an ADR that pretends this conflict has already been decided. A proposal should compare options and impacts, then remain `Pending owner decision` until explicitly approved.
