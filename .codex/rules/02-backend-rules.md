# Backend rules

- Follow Django conventions and the patterns of the selected existing project. Before changing backend code, inspect both `backend/` and `kuzenga/` for overlapping responsibility; canonical ownership remains pending an owner-approved ADR.
- Keep Django apps cohesive and domain-oriented. Separate models, services, serializers, views, permissions, URLs, and tests where complexity warrants; do not create empty layers solely to match a template.
- Models define persistence and basic invariants. Put multi-step business workflows and reusable business decisions in services, not views, serializers, signals, or templates.
- Use serializers for DRF input/output conversion and transport-level validation. Use explicit viewsets/views with narrow responsibilities and route names following existing conventions.
- Enforce authorization in backend permissions, service boundaries, or scoped querysets. A hidden button or filtered UI is not authorization.
- Validate untrusted input at the boundary and enforce critical invariants at the domain/database boundary as appropriate. Raise and translate specific exceptions; never expose tracebacks or secrets to clients.
- Use `transaction.atomic()` for multi-write operations that must succeed or fail together. Make background tasks idempotent and retry-safe; the task queue/provider is not selected by these rules.
- Keep migrations small and review generated SQL and data effects. Follow database rules for destructive or data migrations.
- Use Django's configured logging and timezone-aware datetimes. Do not log passwords, tokens, session identifiers, or sensitive student/financial data.
- Keep settings environment-driven and secrets out of defaults. Add health/readiness behavior without disclosing configuration or internal infrastructure details.
