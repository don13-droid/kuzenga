# Database rules

- PostgreSQL is the intended production database. Follow the selected project's configured database path; do not add a second database or silently fall back in production.
- Model normalized entities with explicit ownership, foreign-key behavior, nullability, uniqueness, and deletion semantics. Denormalize only for a measured need with a consistency plan.
- Add indexes for demonstrated lookup, join, ordering, or uniqueness requirements. Avoid redundant indexes and inspect query plans for important or large queries.
- Prevent N+1 queries with appropriate `select_related`, `prefetch_related`, batching, and pagination. Keep transactions bounded and use atomic transactions for related writes.
- Migrations must be forward-safe and reviewed for locks, runtime, data volume, and deploy order. Prefer expand/migrate/contract for changes that must coexist with older application versions.
- Never introduce a destructive migration, data deletion, irreversible transformation, or broad table rewrite without explicit owner review and approval. Provide a backup/recovery and rollback plan where relevant.
- Protect integrity with database constraints where suitable in addition to application validation. Keep migration data transformations deterministic and tested.
- Tenant-owned rows must be scoped and related within the active tenant. See `modules/tenant-rules.md`; never rely on UI filtering for isolation.
- Backup, restore, retention, and recovery objectives require an operational owner decision; do not claim these are configured without evidence. Test restore procedures before relying on backups.
