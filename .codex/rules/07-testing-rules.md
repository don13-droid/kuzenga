# Testing rules

- Add or update tests for behavior changed by the task. Run the most relevant tests and quality checks before reporting completion; include exact commands and results.
- Cover domain success and failure paths, input boundaries, permissions, and regressions. Security-sensitive work requires denied-access tests, including cross-tenant cases where relevant.
- Keep tests deterministic, isolated, and free of real secrets or external side effects. Mock external systems at clear boundaries; do not mock away the behavior under test.
- Test migrations and important data transformations. For changed queries, check query behavior or performance when material.
- UI changes should cover interaction, validation, empty/error/loading states, accessibility, and responsive layout as appropriate.
- Use each selected project's configured test tools; current backend foundation configures pytest, while existing `kuzenga/` has its own test suite. Do not assume one command covers both projects.
- If dependencies, services, or environment prevent a check, state what was not verified. Do not report an unrun check as passing or silently weaken a test to get a green result.
