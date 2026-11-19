# Subscription access

School access requires both a role permission and an active module entitlement.
An active commercial subscription alone does not authorize a module. Keep checks
on the server through the existing tenancy access services.

## Current catalogue

The seeded plans currently grant these module codes:

| Plan | Module codes |
| --- | --- |
| Starter | `academics`, `students` |
| Standard | Starter plus `attendance`, `assessments` |
| Professional | Standard plus `finance`, `communications` |

Admissions uses the `students` entitlement. User administration and the school
dashboard have role checks but no paid module gate. Student and guardian accounts
do not receive staff permissions from a subscription.

The public quotation catalogue describes a broader feature set, including
Starter attendance and basic fees. It does not change subscription grants. This
commercial mismatch needs a plan/feature decision before changing the seeded
matrix or granting broader access; the repair described below preserves the
existing matrix and permission boundaries.

## Repairing inconsistent grants

A platform superuser can open a school's **Subscriptions** workspace, edit the
affected subscription, provide a reason, and save. The service validates the
plan, module dependencies, status, and dates before synchronizing that record's
plan/trial grants. Saving unchanged fields also repairs missing, duplicated, or
stale grants. A second save with consistent data performs no writes.

The repair preserves independently approved add-ons, exceptions and promotions,
other subscriptions, and other tenants. It uses the stored subscription dates
without extending access; future or expired periods remain inaccessible and
non-access subscription statuses revoke managed grants. A repair without field
changes records `subscription.reconciled` in the audit log and a `reconciled`
subscription event. It runs in the same transaction as the grants, so an audit
failure rolls back the repair.

This code change does not update any deployed tenant's records automatically.
Review and approve production changes before performing production repairs.

Relevant checks: `tests/test_subscriptions.py` and
`tests/test_access_and_entitlements.py`.
