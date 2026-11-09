# Kuzenga contributor instructions

Before changing code or documentation:

1. Read [the rules index](.codex/rules/README.md), then every applicable global rule linked there.
2. Identify the application and module in scope. Read the matching file under `.codex/rules/modules/` and any nearer `AGENTS.md` files.
3. Inspect the existing implementation, tests, settings, and documentation before proposing a new pattern. Check dependencies and conflicts with adjacent modules.
4. Follow the approved architecture and ADRs. The repository currently contains two Django projects (`backend/` and `kuzenga/`); canonical backend authority is unresolved. Do not duplicate or migrate functionality across them without an owner-approved ADR or explicit owner direction.
5. Make the smallest coherent change. Do not add authentication, tenant behavior, business requirements, third-party services, or infrastructure beyond the task scope.
6. Run relevant checks and tests; report commands and results. If environment limitations prevent a check, state that clearly.
7. Update documentation when behavior, interfaces, operations, or architectural decisions change. Do not label a decision approved without evidence of owner approval.
8. In the completion report, name the global and module rules/specifications consulted and any conflicts or pending decisions.

## Instruction discovery and precedence

Follow Codex instruction discovery: this root file applies throughout the repository; inspect and obey any nested `AGENTS.md` closest to the files being changed. More-specific instructions add scope or detail, but do not silently cancel security requirements. Rules in `.codex/rules/` are not assumed to load automatically; consult them explicitly as above.

When guidance conflicts, use the precedence in `.codex/rules/README.md`. If two applicable requirements at the same level conflict, stop the affected decision, explain the conflict, and ask the project owner. A task instruction does not authorize bypassing security or an owner-approved architectural decision.
