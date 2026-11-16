# Kuzenga production release gate record — 16 November 2026

Overall status: BLOCKED. This candidate must not receive production aliases until all critical gates, including real email delivery, pass.

## Baseline and candidate

Latest READY Preview identified through Vercel: `dpl_B8dm3ZzJEMi36rqBBs4YZY7X92mS`,
`https://kuzenga-23mlhui80-donewells-projects.vercel.app`,
commit `de061f7a7cd792dc838aee7a36953e874df04e55`.
PR #1 records earlier live homepage/login/health/static smoke verification for that build; it does not prove authenticated business workflows.

Source candidate starts at `f00b0ca5b0fa83a54c0f898465744b2b4cf76375`
(`integration/local-github-20261115`), exactly three descendant commits ahead of the baseline.
It preserves the Preview foundation, adds tested mobile/portal/subscription corrections and the supplied public branding refresh.
No finance code, business migrations or commercial entitlements differ between these two commits.
Main is `9b54cff4fa8ef34ba51852530ccb1a0409ca45ec`, behind the working Preview, with a failing latest CI run.
Existing draft PRs #1–#3 are not merged by this release preparation.

## Prepared corrections

- Add canonical and social metadata, Organization/WebSite/SoftwareApplication JSON-LD, truthful visible FAQs and both telephone links to both synchronized public templates.
- Keep the supplied approved assets and layout. Do not generate replacement logos.
- Correct public sales contact to sales@elevondigitalzw.com and enquiry delivery default to inquiries@elevondigitalzw.com.
- Permit homepage HEAD requests. Provide robots.txt/sitemap.xml; list only the canonical public homepage. Preview, private, error, query and redirect responses receive X-Robots-Tag restrictions.
- Keep discovery endpoints reachable through optional portal host routing.
- Expose standard SMTP settings through environment variables with a bounded timeout. No Zoho region, mailbox activation or delivery is assumed.
- Correct the production example's public hostname to www.elevondigitalzw.com and use clearly labelled production resource placeholders. Separate portal hosts remain optional proposals, not an applied routing change.
- Add the existing PostgreSQL finance concurrency test as an explicit CI gate. Validate PostgreSQL 16 and the actual Neon major version 18 using disposable CI databases. Keep automatic Vercel Git deployment disabled.

Prepared code requires a fresh CI run. An existing green integration run is not validation of these changes.

## Preparation evidence and acceptance matrix

| Item | Status | Evidence / remaining gate |
| --- | --- | --- |
| Release branch deployed | BLOCKED | No production deployment of this candidate. Release branch release/production-20261116 was confirmed at parent f00b0ca; this correction commit and fresh CI must be checked before release. |
| Exact deployed commit | BLOCKED | No new production SHA; baseline and candidate parent are recorded above. |
| Vercel deployment | FAIL | Only production-target record in 21 returned deployments is ERROR: dpl_4h5TYrzANMMXhoNbDyEr3BG8wWVk, SHA 4539ddd54f4bc707e6106cb8ced3dab47f52f7d5. |
| Production URL | BLOCKED | Intended URL https://www.elevondigitalzw.com/ has not passed live acceptance. |
| Domain configuration | FAIL | Vercel domain lookup reports www and apex misconfigured, with no A/CNAME values. Neither is assigned to this project. |
| Database connection | BLOCKED | Separate production/Preview projects and branches were read successfully; bounded metadata SQL returned no result within 20 seconds on either. Application connectivity unverified. |
| Migrations | BLOCKED | Existing isolated CI applies all migrations; production applied state, upgrade rehearsal and data preservation remain unverified. No production migration performed. |
| Object storage | BLOCKED | Earlier Preview report identifies missing R2 CORS; fresh browser upload/download, credentials, privacy and production isolation remain unverified. |
| Email | BLOCKED | No Zoho admin/mailbox connection. Mailbox activation, licenses, incoming/outgoing and contact-form delivery unverified. DNS alone cannot pass this gate. |
| Authentication | BLOCKED | Existing isolated regressions passed in integration CI; live platform/school/student login/logout and reset workflows remain unverified. |
| Finance | BLOCKED | Integration's ordinary regressions passed, but logs explicitly skip opt-in PostgreSQL concurrency acceptance. New explicit gate, currency/idempotency/concurrency UAT and live synthetic records required. |
| Admissions | BLOCKED | Existing isolated admissions tests included in green integration CI; fresh live synthetic creation/review/approval/rejection/enrolment required. |
| Tenant isolation | BLOCKED | Existing regression coverage is in green integration CI. Live negative cross-tenant students/payments/documents/export checks remain required. |
| Mobile responsiveness | NOT TESTED | Earlier integration documentation records local browser checks; no fresh candidate or production visual verification. |
| SEO | NOT TESTED | Corrections prepared; fresh response/header/XML/schema/mobile/Lighthouse verification required. No performance score claimed. |
| AEO | NOT TESTED | Accurate descriptions and FAQs prepared; rendered production content must be inspected. |
| Security | BLOCKED | No fresh complete security/dependency scan, login abuse validation or production error/storage review. No critical-defect-free claim. |
| CI/CD | PASS | Existing integration run 43746407656 completed successfully: Python 3.12/PostgreSQL16, 461 passed, 2 skipped, migration checks/apply, Ruff and offline deployment/static collection. This is parent-commit evidence only. |
| Remaining scope/issues | BLOCKED | Pricing/catalogue mismatch needs owner resolution; student self-service is absent; teacher directory/attendance are tenant-wide according to role; reset links are administrator-issued. |
| Rollback/recovery | BLOCKED | Preview retained. No successful production rollback candidate found and no database restore rehearsal demonstrated. Procedures below must be completed. |

Fresh verification before the dependency patch: commit 80af0d9ca907df5feae508de82457da855adfc99,
https://github.com/don13-droid/kuzenga/actions/runs/43940790085.
Both PostgreSQL16/18 jobs passed 496 ordinary tests plus the separately executed finance concurrency test, system/migration checks, and strict offline production/static checks.
The first explicit acceptance attempt exposed a fixture defect (base database selected); it was fixed by explicit disposable database setup, pre-setup name guards, and a second guard before seeding. Financial assertions were retained.
The independent dependency audit then found five DRF3.16.1 advisories (PYSEC-2026-3827, PYSEC-2026-3828, GHSA-33wh-fxxf-88vv, GHSA-3547-9m27-7rxg, GHSA-xw6w-gcfp-cf8m).
This candidate pins DRF3.18.2, the audit-reported fix covering all five. Fresh CI/audit must pass after this dependency change.

Fresh baseline HTTP checks through the authenticated Vercel fetch returned HTTP200 for /, /login/, /platform/login/ and /static/css/tailwind.css.
GET /health/ returned HTTP200 with {"status":"ok","database":"ok"} and HTTPS/security headers.
This verifies Preview connectivity through the deployed application, not production connectivity or authenticated workflows.

This table records preparation findings; the release PR description carries the latest exact commit, CI and deployment results.
Parent CI evidence: https://github.com/don13-droid/kuzenga/actions/runs/43746407656
Baseline CI: https://github.com/don13-droid/kuzenga/actions/runs/43418350920
Source scope/recovery evidence: https://github.com/don13-droid/kuzenga/pull/3
Earlier Preview smoke/storage findings: https://github.com/don13-droid/kuzenga/pull/1

The execution environment failed to start with an exec-server readiness timeout.
No local Django, browser, migration, build, security or Lighthouse run is claimed for this candidate.

## Infrastructure observations

Vercel team `team_6QTDl5cFbs90TYvBFjRJvDdk`; project `prj_j7HM2N50WcfQ0NVSIIMIvrtAZbEY`.
Framework Django; authenticated project metadata reports live=false.
All 15 returned environment variables target Preview only; hiddenProductionEnvCount=0.
Production signing key, database, storage, mail, hosts and origins must be configured independently through the secure environment store.
Do not retrieve or copy Preview credentials into Production.
Only assigned domains are preview.kuzenga.elevondigitalzw.com (older chore branch) and kuzenga.vercel.app.
Vercel SSO remains enabled for all except custom domains. No production protection change is made.

Neon production: project delicate-hat-44220525, branch br-proud-flower-b9wz8ynh, aws-eu-central-1.
Preview: project snowy-leaf-13797514, branch br-noisy-fire-beogzk6k, aws-us-east-2.
Both are PostgreSQL18 and have 21600 seconds (six hours) of history retention in returned project metadata.
Production role/database: neondb_owner / neondb.
Production endpoint metadata reports pooler_enabled=false; pooled runtime connectivity must be verified, not inferred from a pooled hostname.
Production list_snapshots returned an empty list. This does not prove that no recoverable history exists.
Restore recoverability, retained backup policy and recovery objectives remain unverified.

## DNS preparation — not applied

Vercel lookup confirms authoritative nameservers launch1.spaceship.net / launch2.spaceship.net for the requested domain.
Obtain a complete zone export at Spaceship before any change, preserving MX, SPF, DKIM, DMARC and verification TXT records.

Current Vercel recommendations from get_domain_config:
- www CNAME: caa0c616193a1bcf.vercel-dns-017.com.
- apex A records: 216.198.79.1 and 64.29.17.1 (rank-one IPv4 set).

Before applying, attach and verify the intended project domains, recheck Vercel recommendations and exact ownership challenges, prepare inverse record changes from the zone export, and confirm existing records do not conflict.
Configure the apex-to-www canonical redirect in Vercel and test the unaliased production artifact before publishing DNS.
These are required record targets, not proof of applied configuration. No nameserver or mail record change is authorized by this document.

## Pricing and product boundaries

Starter begins at USD30, as explicitly specified by the owner and current source.
The existing public catalogue and seeded plan feature matrix conflict. Preserve prices and access controls in this candidate; do not publish the conflicting catalogue until the owner approves a consistent matrix.
No new prices, payment gateway, student self-service or unsupported finance capability is introduced.
No separate approved Kuzenga logo was found in the reviewed public asset inventory; retain supplied assets and request the approved file if required.

## Controlled release and recovery procedure

1. Restore a usable execution environment or equivalent isolated CI/browser runner. Confirm this exact candidate SHA, clean source, passing Python checks, PostgreSQL18 tests including concurrency, dependency scan, asset build and mobile browser UAT.
2. Inspect the production migration graph and applied records without data writes. Create an isolated production-like branch with approved data handling. Rehearse the complete incremental upgrade and verify representative data/invariants.
3. Record a production backup/snapshot and direct-connection logical backup, verify completion, restore into a separate isolated branch and compare schema/migration state and approved aggregate counts. Do not test restoration over production.
4. Review every irreversible migration separately with the owner. Stop writers for any migration whose guards/locks require it. Apply only approved compatible migrations using direct credentials in a controlled one-off step; never migrate on requests or builds.
5. Configure independent Production environment variables/resources, private R2 bucket policy and exact-origin CORS. Complete logo/private-document grants, upload validation and authorized downloads. Verify real Zoho send/receive and contact enquiry delivery using only synthetic enquiries.
6. Stage a production-target build without assigning domains. Capture deployment ID/URL/SHA, project root kuzenga, runtime/build logs, previous alias/redirect mapping, database schema and storage version state. Do not promote a Preview build with different environment settings.
7. Run all acceptance gates against that staged artifact, then promote the same artifact and apply only verified reversible DNS changes with the zone rollback ready. Verify www/apex HTTPS, redirects, static files, auth, tenant isolation, admissions, finance, storage, email and health after promotion.
8. If release checks fail, keep traffic on the previous verified target and investigate logs. Before first production there is no verified production rollback target: explicitly establish the safe first-release failure destination.
9. After a later production cutover, roll application traffic back only to the captured compatible production deployment ID. Restore previous alias/redirect/DNS records from the saved map if needed. Do not assume application rollback reverses schema changes.
10. On migration failure, stop promotion/writers as required, retain logs and migration state, and use a reviewed forward repair unless reversal is demonstrated safe. Restore a verified backup into a new branch first; reconcile intervening writes before changing connection configuration.
11. For storage failures inspect environment selection, bucket/key prefix, signed expiry, CORS, content validation and runtime logs. Never make private buckets public to resolve a download problem.
12. Establish error alert ownership, runtime log access, database monitoring and external health uptime checks. Do not expose credentials, tenant counts, financial records or internal endpoint details through public health responses.

User authorization covers safe preparation and a gated release. Destructive or irreversible operations still require separate approval. This record does not waive any failed or blocked gate.

## Rules consulted

Root AGENTS.md; .codex/rules README and global rules00–10; relevant tenant/authentication/student/admissions/finance/communications/reporting/subscriptions module rules; ADR0001/0002; current deployment, finance, public website and subscription-access documentation.
Explicit current owner instructions authorize the release scope and canonical application root, superseding older preparation-only task statements without changing historical ADR approval status.
