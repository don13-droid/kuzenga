"""Validate new effective dates without rewriting historical allocations."""
from django.db import migrations


def install(apps, editor):
    sqlite = editor.connection.vendor == "sqlite"
    extra = {
        "finance_paymentallocation": """NEW.effective_date IS NOT NULL AND NEW.effective_date<=CURRENT_DATE
            AND EXISTS(SELECT 1 FROM finance_paymentdecision d JOIN finance_journal j ON j.id=d.journal_id
                JOIN finance_invoice i ON i.id=NEW.invoice_id WHERE d.id=NEW.decision_id
                AND NEW.effective_date>=j.date AND NEW.effective_date>=i.issue_date)
            AND NOT EXISTS(SELECT 1 FROM finance_allocationretraction r JOIN finance_paymentallocation a ON a.id=r.allocation_id
                WHERE a.decision_id=NEW.decision_id AND r.date>NEW.effective_date)""",
        "finance_allocationretraction": """EXISTS(SELECT 1 FROM finance_paymentallocation a
            WHERE a.id=NEW.allocation_id AND (a.effective_date IS NULL OR NEW.date>=a.effective_date))""",
    }
    for table, condition in extra.items():
        with editor.connection.cursor() as cursor:
            if sqlite:
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=%s", [table + "_insert_guard"])
            else:
                cursor.execute("SELECT pg_get_functiondef(%s::regprocedure)", [table + "_guard()"])
            definition = cursor.fetchone()[0]
        marker = "SELECT CASE WHEN NOT (" if sqlite else "IF NOT ("
        if definition.count(marker) != 1:
            raise RuntimeError("Expected finance allocation date guard definition not found.")
        definition = definition.replace(marker, marker + "(" + condition + ") AND ", 1)
        if sqlite:
            editor.execute(f"DROP TRIGGER {table}_insert_guard")
        editor.execute(definition)


class Migration(migrations.Migration):
    dependencies = [("finance", "0018_paymentallocation_effective_date")]
    operations = [migrations.RunPython(install)]
