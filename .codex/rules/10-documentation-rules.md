# Documentation rules

- Keep documentation beside its owner: platform rules in `.codex/rules/`, module contracts in module specs, operational steps near the relevant project, and architecture decisions in `docs/architecture/decisions/`.
- Update docs when behavior, APIs, configuration, data handling, operations, or architecture changes. Keep examples runnable and free of real credentials or sensitive data.
- Link related rules, module docs, and ADRs rather than copying long sections. Clearly label assumptions, proposals, pending specifications, and accepted decisions.
- ADRs require a number, title, status, context, decision, alternatives, and consequences. Preserve evidence of approval and do not backdate or infer approval.
- Prefer concise Markdown with descriptive headings, relative links, and actionable language. Remove stale guidance when its owner approves a replacement; do not silently erase historical decisions.
- Completion reports should list relevant rules/specifications consulted, changed files, checks run, limitations, and unresolved decisions.
