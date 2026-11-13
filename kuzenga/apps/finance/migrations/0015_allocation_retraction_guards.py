"""Append-only allocation releases; no posted accounting records are modified."""
from django.db import migrations


def install(apps, editor):
    sqlite = editor.connection.vendor == "sqlite"
    valid = """LENGTH(TRIM(NEW.reason))>0 AND EXISTS(
        SELECT 1 FROM finance_paymentallocation a
        JOIN finance_paymentdecision d ON d.id=a.decision_id
        JOIN finance_journal j ON j.id=d.journal_id
        JOIN tenancy_membership actor ON actor.id=NEW.actor_id
        WHERE a.id=NEW.allocation_id AND a.tenant_id=NEW.tenant_id
        AND actor.tenant_id=NEW.tenant_id AND j.posted
        AND NEW.date>=j.date AND NEW.date<=CURRENT_DATE
        AND NOT EXISTS(SELECT 1 FROM finance_journal r WHERE r.reversal_of_id=j.id)
        AND EXISTS(SELECT 1 FROM finance_accountingperiod p WHERE p.tenant_id=NEW.tenant_id
            AND NOT p.closed AND p.starts_on<=NEW.date AND p.ends_on>=NEW.date))"""
    table = "finance_allocationretraction"
    if sqlite:
        editor.execute(f"CREATE TRIGGER {table}_insert_guard BEFORE INSERT ON {table} BEGIN SELECT CASE WHEN NOT ({valid}) THEN RAISE(ABORT,'Invalid allocation retraction') END; END")
        for action in ("UPDATE", "DELETE"):
            editor.execute(f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Allocation retractions are immutable'); END")
    else:
        editor.execute(f"CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Allocation retractions are immutable'; END IF; PERFORM id FROM finance_paymentallocation WHERE id=NEW.allocation_id FOR UPDATE; IF NOT ({valid}) THEN RAISE EXCEPTION 'Invalid allocation retraction'; END IF; RETURN NEW; END; $$")
        editor.execute(f"CREATE TRIGGER {table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_guard()")
        editor.execute(f"CREATE TRIGGER {table}_truncate_guard BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {table}_guard()")
    # Capacity guards must count only allocations that still designate invoice settlement.
    for table in ("finance_paymentallocation", "finance_invoiceadjustment"):
        with editor.connection.cursor() as cursor:
            if sqlite:
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=%s", [table + "_insert_guard"])
            else:
                cursor.execute("SELECT pg_get_functiondef(%s::regprocedure)", [table + "_guard()"])
            definition = cursor.fetchone()[0]
        needle = "WHERE a.invoice_id=NEW.invoice_id AND d.journal_id IS NOT NULL"
        replacement = "WHERE a.invoice_id=NEW.invoice_id AND NOT EXISTS(SELECT 1 FROM finance_allocationretraction ar WHERE ar.allocation_id=a.id) AND d.journal_id IS NOT NULL"
        if definition.count(needle) != 1:
            raise RuntimeError("Expected invoice settlement guard not found.")
        definition = definition.replace(needle, replacement)
        if table == "finance_paymentallocation":
            needle = "FROM finance_paymentallocation a WHERE a.decision_id=NEW.decision_id)"
            if definition.count(needle) != 1:
                raise RuntimeError("Expected payment allocation capacity guard not found.")
            definition = definition.replace(needle, "FROM finance_paymentallocation a WHERE a.decision_id=NEW.decision_id AND NOT EXISTS(SELECT 1 FROM finance_allocationretraction ar WHERE ar.allocation_id=a.id))")
        if sqlite:
            editor.execute(f"DROP TRIGGER {table}_insert_guard")
        editor.execute(definition)


class Migration(migrations.Migration):
    dependencies = [("finance", "0014_allocationretraction")]
    operations = [migrations.RunPython(install)]
