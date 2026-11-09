# Git rules

- Keep changes focused and reviewable. Preserve unrelated user changes and do not overwrite existing work.
- Use descriptive branch names tied to a feature, fix, or maintenance task. Branch naming is conventional until the repository owner establishes a stricter team policy.
- Use clear commit messages describing the change; do not commit secrets, `.env` files, local databases, build output, or generated artifacts unless the repository explicitly requires them.
- A pull request should explain purpose, implementation, tests, risks, migrations, and any ADR/spec changes. Link relevant issues and decisions when available.
- Require review for security-sensitive changes, architectural changes, destructive migrations, and production operations. Never bypass branch protections or required approvals.
- Keep merge history and release tagging consistent with the repository's existing policy; where none exists, propose a convention rather than inventing a mandatory release scheme.
