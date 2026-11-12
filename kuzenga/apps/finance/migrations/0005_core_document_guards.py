"""Append-only source documents and allocation integrity over the existing ledger."""
from django.core.exceptions import FieldDoesNotExist
from django.db import migrations


def install(apps, editor):
    vendor = editor.connection.vendor
    if vendor not in ("sqlite", "postgresql"):
        raise RuntimeError("Finance documents require SQLite or PostgreSQL.")

    def units(expression):
        return f"CAST(ROUND(({expression})*10000) AS BIGINT)" if vendor == "sqlite" else f"({expression})"

    for name in ["Invoice", "Payment", "PaymentDecision", "PaymentAllocation", "Receipt", "PaymentArrangement", "DebtFollowUp", "FeeRule"]:
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
        if name == "Invoice":
            conditions.append("EXISTS(SELECT 1 FROM finance_feerule f JOIN finance_journalline l ON l.account_id=f.income_account_id WHERE f.id=NEW.fee_id AND l.journal_id=NEW.journal_id AND l.credit=NEW.amount)")
            conditions.append("EXISTS(SELECT 1 FROM finance_feerule f WHERE f.id=NEW.fee_id AND f.currency_id=NEW.currency_id AND f.amount=NEW.amount)")
            conditions.append("EXISTS(SELECT 1 FROM finance_journalline l JOIN finance_account a ON a.id=l.account_id WHERE l.journal_id=NEW.journal_id AND l.student_account_id=NEW.student_account_id AND a.purpose='receivable' AND l.debit=NEW.amount)")
            conditions.append("EXISTS(SELECT 1 FROM finance_journal j WHERE j.id=NEW.journal_id AND j.posted AND j.currency_id=NEW.currency_id AND j.source='student_invoice' AND j.source_reference=NEW.number)")
            conditions.append(f"(SELECT COALESCE(SUM({units('l.debit')}),0) FROM finance_journalline l WHERE l.journal_id=NEW.journal_id)={units('NEW.amount')}")
        if name == "Payment":
            conditions.append("EXISTS(SELECT 1 FROM finance_currency c WHERE c.id=NEW.currency_id AND ROUND(NEW.amount,c.decimal_places)=NEW.amount) AND NEW.amount>0 AND NEW.amount<100000000000")
        if name == "PaymentDecision":
            conditions.append("(NEW.journal_id IS NULL OR EXISTS(SELECT 1 FROM finance_payment p JOIN finance_journalline l ON l.journal_id=NEW.journal_id WHERE p.id=NEW.payment_id AND l.account_id=p.receiving_account_id AND l.debit=p.amount))")
            conditions.append("(NEW.journal_id IS NULL OR EXISTS(SELECT 1 FROM finance_payment p JOIN finance_journalline l ON l.journal_id=NEW.journal_id WHERE p.id=NEW.payment_id AND l.student_account_id=p.student_account_id AND l.account_id=p.receivable_account_id AND l.credit=p.amount))")
            conditions.append("(NEW.journal_id IS NULL OR EXISTS(SELECT 1 FROM finance_payment p JOIN finance_journal j ON j.id=NEW.journal_id WHERE p.id=NEW.payment_id AND j.posted AND j.currency_id=p.currency_id AND j.source='student_payment' AND j.source_reference=p.number))")
        if name == "Receipt":
            conditions.append("EXISTS(SELECT 1 FROM finance_paymentdecision d WHERE d.id=NEW.decision_id AND d.journal_id IS NOT NULL)")
        if name == "PaymentAllocation":
            conditions.append("EXISTS(SELECT 1 FROM finance_invoice i JOIN finance_currency c ON c.id=i.currency_id WHERE i.id=NEW.invoice_id AND ROUND(NEW.amount,c.decimal_places)=NEW.amount)")
            conditions.append("EXISTS(SELECT 1 FROM finance_paymentdecision d JOIN finance_payment p ON p.id=d.payment_id JOIN finance_invoice i ON i.id=NEW.invoice_id WHERE d.id=NEW.decision_id AND d.journal_id IS NOT NULL AND p.student_account_id=i.student_account_id AND p.currency_id=i.currency_id AND NEW.amount>0 AND NOT EXISTS(SELECT 1 FROM finance_journal r WHERE r.reversal_of_id IN (d.journal_id,i.journal_id)))")
            conditions.append(f"{units('NEW.amount')}+(SELECT COALESCE(SUM({units('a.amount')}),0) FROM finance_paymentallocation a WHERE a.decision_id=NEW.decision_id)<=(SELECT {units('p.amount')} FROM finance_payment p JOIN finance_paymentdecision d ON d.payment_id=p.id WHERE d.id=NEW.decision_id)")
            conditions.append(f"{units('NEW.amount')}+(SELECT COALESCE(SUM({units('a.amount')}),0) FROM finance_paymentallocation a JOIN finance_paymentdecision d ON d.id=a.decision_id WHERE a.invoice_id=NEW.invoice_id AND d.journal_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM finance_journal r WHERE r.reversal_of_id=d.journal_id))<=(SELECT {units('i.amount')} FROM finance_invoice i WHERE i.id=NEW.invoice_id)")
        valid = " AND ".join(conditions) or "TRUE"
        if vendor == "sqlite":
            editor.execute(f"CREATE TRIGGER {table}_insert_guard BEFORE INSERT ON {table} BEGIN SELECT CASE WHEN NOT ({valid}) THEN RAISE(ABORT,'Invalid financial source document') END; END")
            for action in ("UPDATE", "DELETE"):
                editor.execute(f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Financial documents are append-only'); END")
        else:
            locks = "PERFORM id FROM finance_paymentdecision WHERE id=NEW.decision_id FOR UPDATE; PERFORM id FROM finance_invoice WHERE id=NEW.invoice_id FOR UPDATE;" if name == "PaymentAllocation" else ""
            editor.execute(f"CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Financial documents are append-only'; END IF; {locks} IF NOT ({valid}) THEN RAISE EXCEPTION 'Invalid financial source document'; END IF; RETURN NEW; END; $$")
            editor.execute(f"CREATE TRIGGER {table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_guard()")
            editor.execute(f"CREATE TRIGGER {table}_truncate_guard BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {table}_guard()")


class Migration(migrations.Migration):
    dependencies = [("finance", "0004_invoice_debtfollowup_payment_paymentarrangement_and_more")]
    operations = [migrations.RunPython(install)]
