# MVP browser acceptance

Run from the canonical `kuzenga/` directory:

```sh
python scripts/check_release_browser.py
```

Install the project's development dependencies and the CI-pinned Playwright/Chromium versions first. The existing Chromium CI job runs this script alongside the public responsive checks and Lighthouse profiles.

## Safety

The harness generates passwords and ADMIN, BURSAR, TEACHER and STUDENT identities in a new temporary SQLite database. It rejects existing database files, unexpected paths and non-SQLite connections before migrating. It starts its own loopback Django process; the workflow refuses an external origin. Financial and student records exist only in this disposable database, which is removed after the process exits. It does not require Production or Preview credentials.

## Accepted workflow

The browser submits actual CSRF-protected application forms to:

1. Submit, review, accept and enrol an admission, preserving guardian/class information and rejecting duplicate conversion without creating a financial charge.
2. Explicitly link the new student to an existing active Student login using the administrator's student-edit form.
3. Configure currency, accounting period, ledger accounts and a USD150 fee; submit reviewed billing twice and verify one invoice/journal.
4. Record a synthetic USD50 bank payment. Verify pending state leaves the balance unchanged and unverified confirmation fails, then confirm and allocate with a synthetic verification reference.
5. Verify the USD100 balance, one receipt/allocation, balanced journals and audit events; retrieve the private PDF and download the collections CSV through the authenticated browser context.
6. Exercise `/finance/debt/` and `/finance/collections/` at desktop/mobile widths.
7. Sign in as Student and Teacher using their passwords, verify permitted personal/class information, reject private administration/finance actions and exercise Student logout.

Read-only database assertions run outside Playwright's event-loop thread and close their connections. They do not replace financial UI writes with service calls. ADMIN posting and BURSAR admissions restrictions remain enforced.

## Evidence boundaries

The fixture seeds the school, subscription, identities and academic class. Platform registration/subscription assignment remain separate integration-test coverage; this script does not claim a browser test of those earlier setup steps. Teacher checks cover the existing shared workspace and assigned-class roster, without claiming a separate new teacher portal.

The script tests synthetic bank verification, not external bank truth, and does not verify Zoho delivery, R2 access, canonical DNS or a live deployment. PostgreSQL integration and concurrency tests remain separate mandatory CI gates. Record exact commit, CI run, test counts and browser output before marking any new acceptance check passed. A green isolated run does not authorize Production promotion.
