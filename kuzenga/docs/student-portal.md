# Student portal MVP

Student users sign in through the existing `/login/` route. Their existing
`/dashboard/` now displays only their explicitly associated student profile and
their own class placement history. It does not grant student-directory,
assessment-management, finance, or platform permissions.

## School administrator setup

1. In **Users & staff**, create the school account with the **Student** role.
2. Deliver its existing secure activation link through the school's approved
   private channel. The student sets their own password; automatic email
   delivery is not added by this change.
3. After activation, open **Students**, create or edit the corresponding student
   record, and explicitly select **Student login account (optional)**.
4. Confirm the correct person and account before saving. A school owner or
   administrator may remove the association by choosing the empty option.

An account is never matched by email, name, date of birth, or admission number.
Only an active, non-platform Student membership in that school can be selected.
One identity may have one explicitly associated student record per school,
consistent with the existing multiple-school membership model. Linking an
account never creates or changes its role or membership.

Changing or suspending membership is checked on subsequent requests. An
unassociated student receives a safe setup message without school totals or
other students' details. Later account suspension or role changes do not block
unrelated student-record updates. The former association remains inert and may
be cleared by a school administrator; newly selected accounts must be eligible.
Association changes are recorded in the existing immutable application audit.

## Migration and deployment

`students.0003_student_portal_user` adds a nullable account foreign key and a
unique constraint on `(tenant_id, portal_user_id)`. Existing rows keep NULL;
there is no inferred mapping, data migration, table reset, or role change.
PostgreSQL receives a real named constraint so future Django constraint
operations agree with the migration state. SQLite uses an equivalent unique
index to avoid rebuilding its referenced student table and established
relations. The regression suite checks uniqueness, the account foreign key,
and PostgreSQL's actual constraint catalogue.

Apply and verify this migration in isolated PostgreSQL and SQLite before any
Preview upgrade. Review migration SQL and verify existing student, enrolment,
guardian and finance references are retained. Production migration and traffic
changes remain controlled release steps. Adding the PostgreSQL constraint
requires a table lock; measure the isolated upgrade and schedule the controlled
release accordingly. For an application rollback, leave the additive
column/constraint in place and restore the compatible previous build.
Reversing the schema removes association data; capture a recoverable backup
and obtain the necessary approval before any destructive production reversal.

`tests/test_student_portal.py` covers own-record rendering, membership changes,
inactive and foreign accounts, multiple-school identity separation, explicit
administrator association, duplicate rejection, entitlement checks and audit
events. These tests must pass alongside the complete PostgreSQL/browser suite
for the exact proposed commit. No real-school acceptance or production success
is inferred from local static inspection.
