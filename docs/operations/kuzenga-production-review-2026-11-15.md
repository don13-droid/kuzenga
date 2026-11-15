# Kuzenga production preparation — 15 November 2026

Status: code changes prepared; production release blocked by outstanding verification and configuration. No deployment, DNS update, production database write, merge or production environment update was performed.

## Prepared changes

- Superuser navigation uses the school portal's mobile drawer behavior: toggle, overlay/Close/Escape dismissal, focus trapping, background inertness and breakpoint focus recovery. Desktop navigation remains visible. The platform menu stays accessible if JavaScript is unavailable.
- Landing pages, school and platform shells, and platform sign-in show `info@elevondigitalzw.com` and `© 2026 Elevon Digital. All rights reserved.` Demo enquiry notifications use the same contact address. The default sender is configurable through `DEFAULT_FROM_EMAIL`.
- Saving an unchanged subscription now reconciles missing, duplicated or stale plan/trial grants and records a `subscription.reconciled` audit event. It preserves independent grants, tenant boundaries and subscription dates. A correct unchanged subscription remains a no-op. Existing production records have not been repaired or inspected successfully.
- Student accounts continue using `/login/` with the existing student role. The dashboard now checks role permissions before querying/displaying school-wide counts. Student sign-in/sign-out, staff/platform denials, inactive/suspended access and cross-tenant session behavior have regression coverage, pending execution. A separate student self-service feature set is not implemented by this change.
- Optional exact-host routing sends each production hostname to its existing portal. All three host settings must be supplied together, be distinct, and be included in `DJANGO_ALLOWED_HOSTS`. Previews leave them blank. Cross-host navigation redirects GET/HEAD only; misplaced POST bodies are rejected rather than forwarded. Authentication, tenant membership and module permissions remain enforced by their existing server-side checks.

## Proposed domain mapping

| Host | Purpose | New setting |
| --- | --- | --- |
| `www.elevondigital.com` | Public landing page | `PUBLIC_SITE_HOST` |
| `platform.kuzenga.elevondigitalzw.com` | Superuser portal | `PLATFORM_SITE_HOST` |
| `kuzenga.elevondigitalzw.com` | School/client/student portal — provisional, awaiting confirmation | `CLIENT_SITE_HOST` |

The owner was asked to confirm the client hostname and whether the landing hostname should instead be `www.elevondigitalzw.com`. The checked-in production example preserves the explicitly requested `.com` hostname and labels the client mapping provisional. This example is documentation, not an applied configuration.

## Read-only infrastructure findings

Vercel account: team `donewells-projects` (`team_6QTDl5cFbs90TYvBFjRJvDdk`), project `kuzenga` (`prj_j7HM2N50WcfQ0NVSIIMIvrtAZbEY`).

| Check | Observed result |
| --- | --- |
| Existing production deployment | Returned deployment `dpl_4h5TYrzANMMXhoNbDyEr3BG8wWVk` is `ERROR` at commit `4539ddd54f4bc707e6106cb8ced3dab47f52f7d5`. |
| Successful preview | `dpl_B8dm3ZzJEMi36rqBBs4YZY7X92mS`, `kuzenga-23mlhui80-donewells-projects.vercel.app`, commit `de061f7a7cd792dc838aee7a36953e874df04e55`. It does not contain this task's changes or all of the newer source branch. |
| Environment separation | All 15 returned Vercel variables target preview; no production variables were returned (`hiddenProductionEnvCount` was zero). Production database, signing, storage and origin configuration must be provisioned before release. |
| Assigned domains | Only `preview.kuzenga.elevondigitalzw.com` and `kuzenga.vercel.app`. The three proposed production hostnames are unassigned. |
| Preview alias | Custom preview hostname remains pinned to `chore/vercel-preview-readiness`, different from the latest successful preview's branch. |
| Automatic deployment | Source `vercel.json` keeps `git.deploymentEnabled=false`; this task did not enable it. |

DNS findings are from Vercel's live domain-configuration inspection, not a registrar account login:

| Host | DNS observation |
| --- | --- |
| `www.elevondigital.com` | GoDaddy nameservers `ns01.domaincontrol.com` / `ns02.domaincontrol.com`; CNAME `elevondigital.com.`; parking A records `3.33.130.190` and `15.197.148.33`; misconfigured for this Vercel project. |
| `platform.kuzenga.elevondigitalzw.com` | Spaceship nameservers `launch1.spaceship.net` / `launch2.spaceship.net`; no A/CNAME returned; misconfigured. |
| `kuzenga.elevondigitalzw.com` | Same Spaceship nameservers; no A/CNAME returned; misconfigured. |
| `preview.kuzenga.elevondigitalzw.com` | Spaceship nameservers, CNAME `caa0c616193a1bcf.vercel-dns-017.com.`; correctly configured. |

Vercel currently recommends `caa0c616193a1bcf.vercel-dns-017.com.` for the project's subdomain CNAMEs. Recheck the recommendation during an approved release. Do not modify mail/MX records or switch nameservers as part of these application changes.

Neon project/branch metadata was readable:

- Existing production project `kuzenga`: `delicate-hat-44220525`, branch `br-proud-flower-b9wz8ynh`, region `aws-eu-central-1`.
- Separate preview project `kuzenga-preview`: `snowy-leaf-13797514`, branch `br-noisy-fire-beogzk6k`, region `aws-us-east-2`.
- Bounded `SELECT 1 AS database_health` attempts against both branches produced no result within 20 seconds. Database connectivity, schema/migration state and deployed entitlements remain unverified. No SQL write was issued.

No authenticated Cloudflare or Spaceship account connector is available in this session. Cloudflare R2 credentials, bucket privacy/CORS, object upload/download and registrar ownership could not be validated. Direct shell HTTP/TLS checks could not run because the sandbox could not reach its configured proxy. Public DNS evidence does not establish authenticated account access or end-to-end application health.

## Checks and limitations

Passed locally:

```sh
cd kuzenga
python -m compileall -q apps config tests scripts
node --check static/js/school-layout.js
node --check static/js/corporate.js
```

The shared drawer script also passed a mock-DOM state smoke check for both school and platform selectors, including open/close, focus trapping, Escape/overlay/link dismissal and breakpoint recovery. This is JavaScript behavior evidence, not a visual browser test.

Attempted application regressions:

```sh
python -m pytest tests/test_subscriptions.py tests/test_access_and_entitlements.py \
  tests/test_portal_hosts.py tests/test_student_login.py \
  tests/test_media_and_navigation.py tests/test_entry_routing.py tests/test_public_website.py
```

The command stopped immediately: `No module named pytest`. Django and other required application dependencies are also absent locally. A temporary Vercel verification sandbox did not return a session and was aborted; no remote suite ran. Chromium could not start under the local sandbox socket restrictions. Therefore no Django, database, visual-browser, migration, production-build or complete end-to-end check is claimed as passing.

`node scripts/check_vercel_config.mjs` also stopped because its untracked `.deployment-tools/schema/node_modules/ajv-draft-04` dependency is absent. The JSON parses and selects the existing Django/WSGI configuration, but full schema validation remains pending.

## Remaining release gates

1. Confirm both outstanding hostname choices. Verify authority to update the chosen landing domain; its current DNS provider differs from the requested Spaceship setup.
2. Restore a working verification environment, install the pinned development requirements, run Ruff, Django checks, migration consistency, the relevant regressions/full suite, offline production/static checks and real mobile/desktop browser flows. Test against an isolated PostgreSQL database.
3. Verify the intended production Neon connection/schema and private Cloudflare R2 operations, including exact-origin CORS and upload/download flows, without copying preview credentials into production.
4. Review production-only Vercel variables and hostname/HTTPS origins, mailbox delivery and the chosen domain assignments. Set the new three-host mapping only for production. Keep preview settings isolated.
5. Resolve the separate public-pricing/catalog mismatch described in [subscription-access.md](../../kuzenga/docs/subscription-access.md). Current tests intentionally keep Starter attendance and Standard finance locked; this patch does not redefine commercial tiers.
6. Obtain the owner's explicit production approval before applying DNS, production environment/database changes, deployment or traffic promotion. Stage and test the intended production artifact before assigning live traffic. Keep a known-good application artifact and compatible database recovery plan available; no new migration is introduced by this patch.

## Source and rules consulted

Prepared against `don13-droid/kuzenga`, source branch `fix/preview-foundation-20261113`, commit `0a73eb995b359f41ca497f59ab038a7544ddaf6a`. The separate `backend/` project was preserved.

Consulted root `AGENTS.md`, `.codex/rules/README.md`, global rules `00`–`10`, module rules for authentication, tenancy, subscriptions and students, ADR-0002, current deployment documentation and existing subscription/access/navigation/login tests. Existing architecture and commercial permission boundaries remain in force. Production is held at the owner's request; outstanding checks and domain choices prevent declaring release readiness.
