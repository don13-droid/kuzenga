# Module rules index

Read the applicable module file whenever changing that module. Also read rules for modules whose data or interfaces the change touches. These files define guardrails and required design questions; they do not approve unprovided product requirements.

Each module specification must address these topics, using `Pending specification` where the owner has not approved details:

1. Module purpose.
2. Functional responsibilities.
3. Database models.
4. Relationships with other modules.
5. Business logic.
6. API endpoints or the reason the module has no API.
7. Authentication and permissions.
8. Tenant isolation.
9. Validation.
10. Error handling.
11. Audit requirements.
12. Automated testing.
13. Dependencies.
14. Integration requirements.

Do not invent missing requirements. A module spec may become detailed only through owner-approved product/architecture decisions. Apply the general backend, database, API, security, and testing rules in addition to the module file.

## Modules

- [Tenant](tenant-rules.md)
- [Authentication](authentication-rules.md)
- [Student](student-rules.md)
- [Admissions](admissions-rules.md)
- [Academics](academics-rules.md)
- [Attendance](attendance-rules.md)
- [Finance](finance-rules.md)
- [Examinations](examinations-rules.md)
- [Communication](communication-rules.md)
- [Reporting](reporting-rules.md)
- [Subscriptions](subscriptions-rules.md)
