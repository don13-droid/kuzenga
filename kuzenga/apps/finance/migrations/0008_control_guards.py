"""Forward-only approval guards and adjusted invoice/payment allocation capacities."""
from django.core.exceptions import FieldDoesNotExist
from django.db import migrations


def install(apps, editor):
    sqlite = editor.connection.vendor == "sqlite"
    if editor.connection.vendor not in ("sqlite", "postgresql"):
        raise RuntimeError("Finance controls require SQLite or PostgreSQL.")

    def units(expr):
        return f"CAST(ROUND(({expr})*10000) AS BIGINT)" if sqlite else f"({expr})"

    adjustment_sum = f"COALESCE((SELECT SUM(CASE WHEN a.direction='debit' THEN {units('a.amount')} ELSE -{units('a.amount')} END) FROM finance_invoiceadjustment a WHERE a.invoice_id=i.id AND NOT EXISTS(SELECT 1 FROM finance_journal z WHERE z.reversal_of_id=a.journal_id)),0)"
    capacity = f"(SELECT {units('i.amount')}+{adjustment_sum} FROM finance_invoice i WHERE i.id=NEW.invoice_id)"
    paid = f"(SELECT COALESCE(SUM({units('a.amount')}),0) FROM finance_paymentallocation a JOIN finance_paymentdecision d ON d.id=a.decision_id WHERE a.invoice_id=NEW.invoice_id AND d.journal_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM finance_journal z WHERE z.reversal_of_id=d.journal_id))"
    refunds = f"COALESCE((SELECT SUM({units('fd.amount')}) FROM finance_financedecision fd JOIN finance_financerequest fr ON fr.id=fd.request_id WHERE fd.approved AND fr.kind='refund' AND fr.payment_id=p.id AND (NOT EXISTS(SELECT 1 FROM finance_refunddisbursement rb WHERE rb.decision_id=fd.id) OR EXISTS(SELECT 1 FROM finance_refunddisbursement rb WHERE rb.decision_id=fd.id AND NOT EXISTS(SELECT 1 FROM finance_journal z WHERE z.reversal_of_id=rb.journal_id)))),0)"

    for name in ["FinanceRequest", "FinanceDecision", "InvoiceAdjustment", "RefundDisbursement", "PaymentAllocation"]:
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
        if name == "FinanceRequest":
            conditions.append("(NEW.invoice_id IS NULL OR EXISTS(SELECT 1 FROM finance_invoice i WHERE i.id=NEW.invoice_id AND i.currency_id=NEW.currency_id AND i.student_account_id=NEW.student_account_id))")
            conditions.append("(NEW.payment_id IS NULL OR EXISTS(SELECT 1 FROM finance_payment p WHERE p.id=NEW.payment_id AND p.currency_id=NEW.currency_id AND p.student_account_id=NEW.student_account_id AND p.receivable_account_id=NEW.receivable_account_id))")
        if name == "FinanceDecision":
            conditions.append("(NEW.journal_id IS NULL OR EXISTS(SELECT 1 FROM finance_journal j WHERE j.id=NEW.journal_id AND j.created_by_id=NEW.actor_id))")
            conditions.append("EXISTS(SELECT 1 FROM finance_financerequest r JOIN tenancy_membership maker ON maker.id=r.requester_id JOIN tenancy_membership reviewer ON reviewer.id=NEW.actor_id WHERE r.id=NEW.request_id AND maker.user_id<>reviewer.user_id)")
            conditions.append("((NOT NEW.approved AND NEW.amount=0 AND NEW.journal_id IS NULL) OR (NEW.approved AND NEW.amount>0 AND EXISTS(SELECT 1 FROM finance_financerequest r WHERE r.id=NEW.request_id AND ((r.kind='refund' AND NEW.journal_id IS NULL) OR EXISTS(SELECT 1 FROM finance_invoiceadjustment a WHERE a.request_id=r.id AND a.journal_id=NEW.journal_id AND a.amount=NEW.amount)))))")
        if name == "InvoiceAdjustment":
            conditions.append("EXISTS(SELECT 1 FROM finance_financerequest r JOIN finance_journalline l ON l.journal_id=NEW.journal_id WHERE r.id=NEW.request_id AND l.account_id=r.receivable_account_id AND l.student_account_id=r.student_account_id AND ((r.kind='debit' AND NEW.direction='debit' AND l.debit=NEW.amount) OR (r.kind NOT IN ('debit','refund') AND NEW.direction='credit' AND l.credit=NEW.amount)))")
            conditions.append("EXISTS(SELECT 1 FROM finance_financerequest r JOIN finance_journalline l ON l.journal_id=NEW.journal_id WHERE r.id=NEW.request_id AND l.account_id=r.counter_account_id AND ((NEW.direction='debit' AND l.credit=NEW.amount) OR (NEW.direction='credit' AND l.debit=NEW.amount)))")
            conditions.append("EXISTS(SELECT 1 FROM finance_invoice i JOIN finance_financerequest r ON r.invoice_id=i.id JOIN finance_journal j ON j.id=NEW.journal_id WHERE i.id=NEW.invoice_id AND r.id=NEW.request_id AND j.posted AND j.currency_id=i.currency_id AND j.source='invoice_adjustment' AND j.source_reference=r.number AND NOT EXISTS(SELECT 1 FROM finance_journal z WHERE z.reversal_of_id=i.journal_id))")
            conditions.append(f"NEW.amount>0 AND {capacity}+(CASE WHEN NEW.direction='debit' THEN {units('NEW.amount')} ELSE -{units('NEW.amount')} END)>={paid}")
            conditions.append("EXISTS(SELECT 1 FROM finance_invoice i JOIN finance_currency c ON c.id=i.currency_id WHERE i.id=NEW.invoice_id AND ROUND(NEW.amount,c.decimal_places)=NEW.amount)")
        if name == "RefundDisbursement":
            conditions.append("EXISTS(SELECT 1 FROM finance_financedecision d JOIN finance_financerequest r ON r.id=d.request_id JOIN finance_journalline l ON l.journal_id=NEW.journal_id JOIN finance_journal j ON j.id=NEW.journal_id WHERE d.id=NEW.decision_id AND l.account_id=r.receivable_account_id AND l.student_account_id=r.student_account_id AND l.debit=d.amount AND j.created_by_id=NEW.actor_id)")
            conditions.append("EXISTS(SELECT 1 FROM finance_financedecision d JOIN finance_financerequest r ON r.id=d.request_id JOIN finance_journalline l ON l.journal_id=NEW.journal_id WHERE d.id=NEW.decision_id AND l.account_id=r.counter_account_id AND l.credit=d.amount)")
            conditions.append("EXISTS(SELECT 1 FROM finance_financedecision d JOIN finance_financerequest r ON r.id=d.request_id JOIN finance_journal j ON j.id=NEW.journal_id JOIN tenancy_membership approver ON approver.id=d.actor_id JOIN tenancy_membership cashier ON cashier.id=NEW.actor_id WHERE d.id=NEW.decision_id AND d.approved AND r.kind='refund' AND j.posted AND j.currency_id=r.currency_id AND j.source='refund_disbursement' AND j.source_reference=r.number AND approver.user_id<>cashier.user_id)")
        if name == "PaymentAllocation":
            conditions.append("EXISTS(SELECT 1 FROM finance_paymentdecision d JOIN finance_payment p ON p.id=d.payment_id JOIN finance_invoice i ON i.id=NEW.invoice_id JOIN finance_currency c ON c.id=i.currency_id WHERE d.id=NEW.decision_id AND d.journal_id IS NOT NULL AND p.student_account_id=i.student_account_id AND p.currency_id=i.currency_id AND ROUND(NEW.amount,c.decimal_places)=NEW.amount AND NEW.amount>0 AND NOT EXISTS(SELECT 1 FROM finance_journal z WHERE z.reversal_of_id IN (d.journal_id,i.journal_id)))")
            conditions.append(f"{units('NEW.amount')}+{paid}<={capacity}")
            conditions.append(f"{units('NEW.amount')}+(SELECT COALESCE(SUM({units('a.amount')}),0) FROM finance_paymentallocation a WHERE a.decision_id=NEW.decision_id)<=(SELECT {units('p.amount')}-{refunds} FROM finance_payment p JOIN finance_paymentdecision d ON d.payment_id=p.id WHERE d.id=NEW.decision_id)")
        valid = " AND ".join(conditions)
        if sqlite:
            if name == "PaymentAllocation":
                editor.execute("DROP TRIGGER finance_paymentallocation_insert_guard")
            editor.execute(f"CREATE TRIGGER {table}_insert_guard BEFORE INSERT ON {table} BEGIN SELECT CASE WHEN NOT ({valid}) THEN RAISE(ABORT,'Invalid approved finance control') END; END")
            if name != "PaymentAllocation":
                for action in ("UPDATE", "DELETE"):
                    editor.execute(f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Finance controls are append-only'); END")
        else:
            locks = "PERFORM id FROM finance_invoice WHERE id=NEW.invoice_id FOR UPDATE;" if name == "InvoiceAdjustment" else "PERFORM id FROM finance_paymentdecision WHERE id=NEW.decision_id FOR UPDATE; PERFORM id FROM finance_invoice WHERE id=NEW.invoice_id FOR UPDATE;" if name == "PaymentAllocation" else ""
            editor.execute(f"CREATE OR REPLACE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Finance controls are append-only'; END IF; {locks} IF NOT ({valid}) THEN RAISE EXCEPTION 'Invalid approved finance control'; END IF; RETURN NEW; END; $$")
            if name != "PaymentAllocation":
                editor.execute(f"CREATE TRIGGER {table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_guard()")
                editor.execute(f"CREATE TRIGGER {table}_truncate_guard BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {table}_guard()")


class Migration(migrations.Migration):
    dependencies = [("finance", "0007_financerequest_payment")]
    operations = [migrations.RunPython(install)]
