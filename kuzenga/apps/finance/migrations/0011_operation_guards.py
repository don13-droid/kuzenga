"""Immutable operational history, separate reviewers and tenant-safe source relationships."""
from django.core.exceptions import FieldDoesNotExist
from django.db import migrations


def install(apps, editor):
    sqlite = editor.connection.vendor == "sqlite"
    if editor.connection.vendor not in ("sqlite", "postgresql"):
        raise RuntimeError("Finance operations require SQLite or PostgreSQL.")
    def units(value):
        return f"CAST(ROUND(({value})*10000) AS BIGINT)" if sqlite else f"({value})"
    for name in ["CashSession", "CashSubmission", "CashReview", "FinanceImport", "ImportDecision", "StatementRow", "OpeningEntry", "ReconciliationMatch", "MatchDecision", "ReconciledEntry"]:
        model = apps.get_model("finance", name)
        table = model._meta.db_table
        conditions = []
        for field in model._meta.concrete_fields:
            if not field.is_relation or field.name == "tenant":
                continue
            related = field.related_model
            try:
                related._meta.get_field("tenant")
            except FieldDoesNotExist:
                continue
            conditions.append(f"(NEW.{field.column} IS NULL OR EXISTS(SELECT 1 FROM {related._meta.db_table} r WHERE r.id=NEW.{field.column} AND r.tenant_id=NEW.tenant_id))")
        if name == "CashSession":
            conditions.append("NEW.opening_float>=0 AND EXISTS(SELECT 1 FROM finance_account a WHERE a.id=NEW.account_id AND a.kind='asset' AND a.purpose='cash')")
        if name == "CashSubmission":
            conditions.append(f"NEW.actual>=0 AND {units('NEW.difference')}={units('NEW.actual')}-{units('NEW.expected')}")
        if name == "CashReview":
            conditions.append("EXISTS(SELECT 1 FROM finance_cashsubmission s JOIN finance_cashsession c ON c.id=s.session_id JOIN tenancy_membership maker ON maker.id=c.cashier_id JOIN tenancy_membership reviewer ON reviewer.id=NEW.actor_id WHERE s.id=NEW.submission_id AND maker.user_id<>reviewer.user_id)")
        if name == "ImportDecision":
            conditions.append("EXISTS(SELECT 1 FROM finance_financeimport b JOIN tenancy_membership maker ON maker.id=b.requester_id JOIN tenancy_membership reviewer ON reviewer.id=NEW.actor_id WHERE b.id=NEW.batch_id AND maker.user_id<>reviewer.user_id)")
        if name == "StatementRow":
            conditions.append("NEW.amount<>0 AND EXISTS(SELECT 1 FROM finance_financeimport b WHERE b.id=NEW.batch_id AND b.kind='statement' AND b.account_id=NEW.account_id AND b.currency_id=NEW.currency_id)")
        if name == "OpeningEntry":
            conditions.append("NEW.amount<>0 AND EXISTS(SELECT 1 FROM finance_journal j JOIN finance_financeimport b ON b.id=NEW.batch_id WHERE j.id=NEW.journal_id AND j.posted AND j.currency_id=NEW.currency_id AND j.source='opening_import' AND b.kind='opening' AND REPLACE(j.source_reference,'-','')=REPLACE(CAST(NEW.batch_id AS TEXT),'-',''))")
            conditions.append("EXISTS(SELECT 1 FROM finance_journalline l JOIN finance_financeimport b ON b.id=NEW.batch_id WHERE l.journal_id=NEW.journal_id AND l.student_account_id=NEW.student_account_id AND l.account_id=b.receivable_id AND l.debit-l.credit=NEW.amount)")
        if name == "ReconciliationMatch":
            conditions.append("EXISTS(SELECT 1 FROM finance_statementrow r JOIN finance_journalline l ON l.id=NEW.line_id JOIN finance_journal j ON j.id=l.journal_id WHERE r.id=NEW.row_id AND r.account_id=l.account_id AND r.currency_id=j.currency_id AND r.amount=l.debit-l.credit AND j.posted)")
        if name == "MatchDecision":
            conditions.append("EXISTS(SELECT 1 FROM finance_reconciliationmatch m JOIN tenancy_membership maker ON maker.id=m.requester_id JOIN tenancy_membership reviewer ON reviewer.id=NEW.actor_id WHERE m.id=NEW.match_id AND maker.user_id<>reviewer.user_id)")
        if name == "ReconciledEntry":
            conditions.append("EXISTS(SELECT 1 FROM finance_matchdecision d JOIN finance_reconciliationmatch m ON m.id=d.match_id WHERE d.id=NEW.decision_id AND d.approved AND m.row_id=NEW.row_id AND m.line_id=NEW.line_id)")
        valid = " AND ".join(conditions) or "TRUE"
        if sqlite:
            editor.execute(f"CREATE TRIGGER {table}_insert_guard BEFORE INSERT ON {table} BEGIN SELECT CASE WHEN NOT ({valid}) THEN RAISE(ABORT,'Invalid finance operation') END; END")
            for action in ("UPDATE", "DELETE"):
                editor.execute(f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Finance operational history is immutable'); END")
        else:
            editor.execute(f"CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Finance operational history is immutable'; END IF; IF NOT ({valid}) THEN RAISE EXCEPTION 'Invalid finance operation'; END IF; RETURN NEW; END; $$")
            editor.execute(f"CREATE TRIGGER {table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_guard()")
            editor.execute(f"CREATE TRIGGER {table}_truncate_guard BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {table}_guard()")


class Migration(migrations.Migration):
    dependencies = [("finance", "0010_alter_financeimport_errors_alter_financeimport_rows")]
    operations = [migrations.RunPython(install)]
