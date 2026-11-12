"""Immutable refund closures and release of cancelled approval reservations."""
from django.db import migrations


def install(apps, editor):
    sqlite = editor.connection.vendor == "sqlite"
    valid = """EXISTS(SELECT 1 FROM finance_financedecision d JOIN finance_financerequest r ON r.id=d.request_id
        JOIN tenancy_membership actor ON actor.id=NEW.actor_id JOIN tenancy_membership maker ON maker.id=r.requester_id
        JOIN tenancy_membership approver ON approver.id=d.actor_id WHERE d.id=NEW.decision_id AND d.tenant_id=NEW.tenant_id
        AND actor.tenant_id=NEW.tenant_id AND d.approved AND r.kind='refund' AND actor.user_id<>maker.user_id
        AND actor.user_id<>approver.user_id AND
        ((NEW.journal_id IS NULL AND NOT EXISTS(SELECT 1 FROM finance_refunddisbursement rb WHERE rb.decision_id=d.id))
        OR EXISTS(SELECT 1 FROM finance_refunddisbursement rb JOIN finance_journal j ON j.reversal_of_id=rb.journal_id
        WHERE rb.decision_id=d.id AND j.id=NEW.journal_id AND j.tenant_id=NEW.tenant_id AND j.posted)))"""
    if sqlite:
        editor.execute(f"CREATE TRIGGER finance_refundclosure_insert_guard BEFORE INSERT ON finance_refundclosure BEGIN SELECT CASE WHEN NOT ({valid}) THEN RAISE(ABORT,'Invalid refund closure') END; END")
        for action in ("UPDATE", "DELETE"):
            editor.execute(f"CREATE TRIGGER finance_refundclosure_{action.lower()}_guard BEFORE {action} ON finance_refundclosure BEGIN SELECT RAISE(ABORT,'Refund closures are immutable'); END")
        with editor.connection.cursor() as cursor:
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='finance_paymentallocation_insert_guard'")
            definition = cursor.fetchone()[0]
    else:
        editor.execute(f"CREATE FUNCTION finance_refundclosure_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Refund closures are immutable'; END IF; IF NOT ({valid}) THEN RAISE EXCEPTION 'Invalid refund closure'; END IF; RETURN NEW; END; $$")
        editor.execute("CREATE TRIGGER finance_refundclosure_guard BEFORE INSERT OR UPDATE OR DELETE ON finance_refundclosure FOR EACH ROW EXECUTE FUNCTION finance_refundclosure_guard()")
        editor.execute("CREATE TRIGGER finance_refundclosure_truncate_guard BEFORE TRUNCATE ON finance_refundclosure FOR EACH STATEMENT EXECUTE FUNCTION finance_refundclosure_guard()")
        with editor.connection.cursor() as cursor:
            cursor.execute("SELECT pg_get_functiondef('finance_paymentallocation_guard()'::regprocedure)")
            definition = cursor.fetchone()[0]
    needle = "fd.approved AND fr.kind='refund'"
    if definition.count(needle) != 1:
        raise RuntimeError("Expected refund reservation guard was not found; do not weaken allocation protection.")
    definition = definition.replace(needle, "fd.approved AND NOT EXISTS(SELECT 1 FROM finance_refundclosure rc WHERE rc.decision_id=fd.id) AND fr.kind='refund'")
    if sqlite:
        editor.execute("DROP TRIGGER finance_paymentallocation_insert_guard")
    editor.execute(definition)


class Migration(migrations.Migration):
    dependencies = [("finance", "0012_refundclosure")]
    operations = [migrations.RunPython(install)]
