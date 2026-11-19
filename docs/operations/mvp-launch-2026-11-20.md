# MVP launch checklist — 20 November 2026

Status on 19 November: **BLOCKED; production traffic must remain unchanged.**

The owner authorized safe stabilization, isolated tests and Preview preparation, and requires explicit final approval before any Production traffic switch. This record supplements the historical ADRs without changing their approval status.

## Verified baseline

- Four permanent branches exist: `main`, `develop`, `release`, `preview`. Two legacy branches remain protected pending all deletion safeguards.
- Release `633907cb949ed03355c9df86c0fb5d245baf6fa3` passed [CI run 44367563241](https://github.com/don13-droid/kuzenga/actions/runs/44367563241). PostgreSQL 16 and 18 each passed 496 tests with two documented skips, plus one separately executed concurrency acceptance test. The dependency audit and public/school/platform Chromium checks passed.
- Develop `e9b1f6dbe9d1972e5fefb3e4f6e21f9a1938db47` adds only dispatcher documentation to that release.
- Latest inspected READY Preview is `dpl_6e5dzGwadgS3b1WZ3DLZ4Aj1pZGP`, SHA `0a73eb995b359f41ca497f59ab038a7544ddaf6a`, from permanent `preview`. It is nine commits behind the verified release. READY is build metadata, not authenticated workflow evidence.

## Completion gates

- [ ] Correct the conflicting public pricing catalogue without changing subscriptions or entitlements; publish only confirmed Starter from USD 30 per school term and request quotations for other plans.
- [ ] Run the existing CI gates on pushes and pull requests for all four permanent branches. A green build does not authorize a Production promotion.
- [ ] Verify the final commit with fresh CI after application/test changes. Retain exact passing, failing and skipped counts.
- [ ] Complete browser acceptance for onboarding, admission, enrolment, billing, recorded payment, receipt and reporting using disposable tenants; preserve financial role separation.
- [ ] Resolve the student self-service/dashboard gap with a reviewed scope and negative authorization tests. Existing Student Login currently opens an empty generic workspace.
- [ ] Verify teacher password login and existing assigned-work workflows; do not claim a dedicated teacher portal from a generic dashboard.
- [ ] Advance permanent `preview` through reviewed changes and verify HTTPS, health, authentication, static/media and error responses for the exact final SHA.
- [ ] Change only the Preview domain's persistent Git assignment from `chore/vercel-preview-readiness` to `preview` using the supported project-domain PATCH operation; retain the previous deployment and inverse request.
- [ ] Verify actual R2 authentication, private upload/download, expired/unauthorized rejection, tenant isolation, content validation, browser rendering and exact-origin CORS. Do not make a private bucket public to resolve access failures.
- [ ] Verify current Preview migration rows and a current-schema snapshot restore into a separate branch. The restored November 13 snapshot has only 43 tables versus the current 85 and is insufficient as current-application recovery evidence.
- [ ] Rehearse the reviewed Django migration graph against an isolated empty Production-baseline restore. Never fake migration rows or run migrations from requests/builds.
- [ ] Install independent Production database, storage, SMTP and Django settings using secure environment stores. The inspected Production environment currently exposes only a configured signing-key entry; no value is recorded here.
- [ ] Verify canonical domains, TLS, redirects and mail authentication at the authoritative provider without changing Production traffic or unrelated records.
- [ ] Verify Zoho mailbox activation, incoming/outgoing mail and contact-enquiry delivery. DNS records alone do not establish email delivery.
- [ ] Test application rollback separately from database recovery and record the actual deployment IDs, schema compatibility and retention limits.
- [ ] Preserve the legacy chore branch's unique commit with a recoverable reference; remove legacy branches only after Preview/domain/workflow dependencies and all owner-specified safeguards pass.
- [ ] Confirm no unresolved P0 or launch-blocking P1 issue, then request explicit approval for the concrete Production release procedure.

## Pilot-school operations

1. A platform administrator creates and activates the school, assigns its subscription and provisions its school administrator.
2. Configure school contacts, branding, academic year, term, classes and subjects before importing/entering students.
3. Confirm module entitlements and roles. Finance posting requires the intended finance principal, while controlled approval/reversal remains a separate authorized action; do not grant posting to every school administrator to simplify onboarding.
4. Demonstrate admission/enrolment, fee setup, one synthetic payment and receipt, and essential reports in the isolated acceptance environment before using real records.
5. Confirm support contacts, opening-balance procedure, responsible finance approver, backup owner and recovery steps with the pilot school. No payment gateway or automatic subscription charging is part of this launch.

The current command environment cannot reach its managed network proxy. Existing CI results remain valid for their exact SHA; new code and infrastructure acceptance must not be marked passed until executed successfully through a working runner/connection.
