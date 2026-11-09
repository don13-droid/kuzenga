# Frontend rules

- Preserve the existing documented UI architecture: Django templates with HTMX and Tailwind in `kuzenga/`. Inspect current templates, components, and styling before adding or replacing a pattern.
- Reuse established layouts, form controls, and visual tokens. Keep accessible semantic HTML, keyboard operation, visible focus, labels, useful error messages, and responsive behavior.
- Keep server-rendered UI behavior understandable. Use HTMX for targeted interactions consistent with existing usage; do not introduce another UI framework, client state system, build pipeline, or duplicate component library without an owner-approved ADR.
- Integrate with backend endpoints through the established request flow. Include loading, success, empty, and error states as appropriate; do not leak server errors or rely on client checks for authorization.
- Validate forms on the server. Client-side validation may improve usability but cannot replace backend validation.
- Avoid unnecessary scripts, large assets, repeated requests, or unbounded DOM updates. Preserve the approved Kuzenga identity and test changed layouts at narrow and wide viewports.
- Accessibility and responsive checks should be included in relevant UI tests or review evidence.
