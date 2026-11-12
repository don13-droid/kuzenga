"""Keep match history while preventing duplicate active matches after a release."""
from django.db import migrations


def install(apps, editor):
    sqlite = editor.connection.vendor == "sqlite"
    conditions = {
        "finance_reconciliationrelease": """LENGTH(TRIM(NEW.reason))>0 AND EXISTS(
            SELECT 1 FROM finance_reconciledentry e
            JOIN finance_matchdecision d ON d.id=e.decision_id
            JOIN finance_reconciliationmatch m ON m.id=d.match_id
            JOIN tenancy_membership actor ON actor.id=NEW.actor_id
            JOIN tenancy_membership approver ON approver.id=d.actor_id
            JOIN tenancy_membership maker ON maker.id=m.requester_id
            WHERE e.id=NEW.entry_id AND e.tenant_id=NEW.tenant_id
            AND actor.tenant_id=NEW.tenant_id AND actor.user_id<>approver.user_id
            AND actor.user_id<>maker.user_id)""",
        "finance_reconciledentry": """EXISTS(SELECT 1 FROM finance_matchdecision d
            JOIN finance_reconciliationmatch m ON m.id=d.match_id
            JOIN finance_statementrow r ON r.id=NEW.row_id
            JOIN finance_journalline l ON l.id=NEW.line_id
            JOIN finance_journal j ON j.id=l.journal_id
            WHERE d.id=NEW.decision_id AND d.tenant_id=NEW.tenant_id AND d.approved
            AND r.tenant_id=NEW.tenant_id AND l.tenant_id=NEW.tenant_id
            AND m.row_id=r.id AND m.line_id=l.id AND r.currency_id=j.currency_id
            AND r.account_id=l.account_id AND r.amount=l.debit-l.credit AND j.posted
            AND NOT EXISTS(SELECT 1 FROM finance_journal z WHERE z.reversal_of_id=j.id))
            AND NOT EXISTS(SELECT 1 FROM finance_reconciledentry e
            WHERE (e.row_id=NEW.row_id OR e.line_id=NEW.line_id)
            AND NOT EXISTS(SELECT 1 FROM finance_reconciliationrelease r WHERE r.entry_id=e.id))""",
    }
    for table, valid in conditions.items():
        if sqlite:
            # SQLite's table rebuild for FK cardinality can drop the earlier table guards.
            for action in ("insert", "update", "delete"):
                editor.execute(f"DROP TRIGGER IF EXISTS {table}_{action}_guard")
            editor.execute(f"CREATE TRIGGER {table}_insert_guard BEFORE INSERT ON {table} BEGIN SELECT CASE WHEN NOT ({valid}) THEN RAISE(ABORT,'Invalid reconciliation correction') END; END")
            for action in ("UPDATE", "DELETE"):
                editor.execute(f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Reconciliation history is immutable'); END")
        else:
            locks = "PERFORM id FROM finance_statementrow WHERE id=NEW.row_id FOR UPDATE; PERFORM id FROM finance_journalline WHERE id=NEW.line_id FOR UPDATE;" if table == "finance_reconciledentry" else "PERFORM id FROM finance_reconciledentry WHERE id=NEW.entry_id FOR UPDATE;"
            editor.execute(f"CREATE OR REPLACE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Reconciliation history is immutable'; END IF; {locks} IF NOT ({valid}) THEN RAISE EXCEPTION 'Invalid reconciliation correction'; END IF; RETURN NEW; END; $$")
            if table == "finance_reconciliationrelease":
                editor.execute(f"CREATE TRIGGER {table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_guard()")
                editor.execute(f"CREATE TRIGGER {table}_truncate_guard BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {table}_guard()")


class Migration(migrations.Migration):
    dependencies = [("finance", "0016_alter_reconciledentry_line_alter_reconciledentry_row_and_more")]
    operations = [migrations.RunPython(install)]
