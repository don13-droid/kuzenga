# Global development rules

- Keep Kuzenga a modular monolith unless an owner-approved ADR authorizes a different deployment or service boundary.
- Inspect existing implementations before adding a package, app, service, shared helper, configuration, or dependency. Reuse a sound existing capability; avoid duplicate sources of truth.
- Keep responsibilities clear: domain rules belong in domain services/models, transport and presentation in views/serializers/templates, and persistence in repositories only where an established pattern requires them.
- Prefer simple, cohesive, testable changes over speculative abstractions. Share code only when the behavior and ownership are genuinely shared.
- Use established naming conventions: Python modules/functions/variables `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`, and descriptive URL/API names. Follow the existing frontend conventions in touched files.
- Pin or bound dependencies in the project's existing dependency mechanism. Add only necessary dependencies; explain material runtime, licensing, and security impacts.
- Handle expected errors deliberately, return safe and consistent responses, and log actionable context without secrets or unnecessary personal data. Do not hide failures with broad exception handling.
- Consider query count, payload size, pagination, indexes, caching, and background work where they materially affect the changed path. Measure or explain performance-sensitive choices.
- Preserve existing interfaces and data behavior unless a planned breaking change is approved, documented, tested, and communicated.
- Keep UTC-aware datetimes and follow configured timezone behavior. Never store credentials in source, fixtures, logs, or committed environment files.
- Do not modify unrelated user work. Do not add business functionality outside the task.
