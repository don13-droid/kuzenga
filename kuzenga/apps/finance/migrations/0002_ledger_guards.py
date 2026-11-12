"""Database guards supplement service validation; no existing domain tables are altered."""
from django.db import migrations


def install(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    # SQL uses static schema identifiers only. Every FK must share the journal's tenant.
    header_valid = """EXISTS (SELECT 1 FROM finance_accountingperiod p WHERE p.id=NEW.period_id AND p.tenant_id=NEW.tenant_id AND NOT p.closed AND NEW.date BETWEEN p.starts_on AND p.ends_on)
        AND EXISTS (SELECT 1 FROM finance_currency c WHERE c.id=NEW.currency_id AND c.tenant_id=NEW.tenant_id AND c.is_active)
        AND EXISTS (SELECT 1 FROM tenancy_membership m WHERE m.id=NEW.created_by_id AND m.tenant_id=NEW.tenant_id)
        AND (NEW.reversal_of_id IS NULL OR EXISTS (SELECT 1 FROM finance_journal j WHERE j.id=NEW.reversal_of_id AND j.tenant_id=NEW.tenant_id AND j.currency_id=NEW.currency_id AND j.posted))
        AND NOT EXISTS(SELECT 1 FROM finance_journalline l JOIN finance_currency c ON c.id=NEW.currency_id WHERE l.journal_id=NEW.id AND (l.tenant_id<>NEW.tenant_id OR ROUND(l.debit,c.decimal_places)<>l.debit OR ROUND(l.credit,c.decimal_places)<>l.credit))"""
    line_valid = """EXISTS (SELECT 1 FROM finance_journal j WHERE j.id=NEW.journal_id AND j.tenant_id=NEW.tenant_id AND NOT j.posted)
        AND EXISTS (SELECT 1 FROM finance_account a WHERE a.id=NEW.account_id AND a.tenant_id=NEW.tenant_id AND a.is_active AND ((a.purpose='receivable' AND NEW.student_account_id IS NOT NULL) OR (a.purpose<>'receivable' AND NEW.student_account_id IS NULL)))
        AND (NEW.student_account_id IS NULL OR EXISTS (SELECT 1 FROM finance_studentaccount s WHERE s.id=NEW.student_account_id AND s.tenant_id=NEW.tenant_id))
        AND NEW.debit>=0 AND NEW.credit>=0 AND NEW.debit<100000000000 AND NEW.credit<100000000000
        AND EXISTS(SELECT 1 FROM finance_journal j JOIN finance_currency c ON c.id=j.currency_id WHERE j.id=NEW.journal_id AND ROUND(NEW.debit,c.decimal_places)=NEW.debit AND ROUND(NEW.credit,c.decimal_places)=NEW.credit)"""
    balanced = """(SELECT COUNT(*) FROM finance_journalline l WHERE l.journal_id=NEW.id)>=2
        AND (SELECT COALESCE(SUM(l.debit-l.credit),0) FROM finance_journalline l WHERE l.journal_id=NEW.id)=0"""
    if vendor == "sqlite":
        balanced = """(SELECT COUNT(*) FROM finance_journalline l WHERE l.journal_id=NEW.id)>=2
            AND (SELECT SUM(CAST(ROUND(l.debit*10000) AS INTEGER)-CAST(ROUND(l.credit*10000) AS INTEGER)) FROM finance_journalline l WHERE l.journal_id=NEW.id)=0"""
        statements = {
            "journal_insert": f"BEFORE INSERT ON finance_journal BEGIN SELECT CASE WHEN NEW.posted OR NOT ({header_valid}) THEN RAISE(ABORT,'Invalid journal header') END; END",
            "journal_update": f"BEFORE UPDATE ON finance_journal BEGIN SELECT CASE WHEN OLD.posted OR NOT NEW.posted OR NOT ({header_valid}) OR NOT ({balanced}) THEN RAISE(ABORT,'Posted journal is immutable or unbalanced') END; END",
            "journal_delete": "BEFORE DELETE ON finance_journal BEGIN SELECT RAISE(ABORT,'Ledger deletion forbidden'); END",
            "line_insert": f"BEFORE INSERT ON finance_journalline BEGIN SELECT CASE WHEN NOT ({line_valid}) THEN RAISE(ABORT,'Invalid or frozen ledger line') END; END",
            "line_update": "BEFORE UPDATE ON finance_journalline BEGIN SELECT RAISE(ABORT,'Ledger line update forbidden'); END",
            "line_delete": "BEFORE DELETE ON finance_journalline BEGIN SELECT RAISE(ABORT,'Ledger line deletion forbidden'); END",
            "student_insert": "BEFORE INSERT ON finance_studentaccount BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM students_student s WHERE s.id=NEW.student_id AND s.tenant_id=NEW.tenant_id) THEN RAISE(ABORT,'Student tenant mismatch') END; END",
            "student_update": "BEFORE UPDATE ON finance_studentaccount BEGIN SELECT CASE WHEN NEW.student_id<>OLD.student_id OR NEW.tenant_id<>OLD.tenant_id THEN RAISE(ABORT,'Financial identity cannot change') END; END",
            "account_update": "BEFORE UPDATE ON finance_account WHEN EXISTS(SELECT 1 FROM finance_journalline l WHERE l.account_id=OLD.id) BEGIN SELECT CASE WHEN NEW.code<>OLD.code OR NEW.kind<>OLD.kind OR NEW.purpose<>OLD.purpose OR NEW.tenant_id<>OLD.tenant_id THEN RAISE(ABORT,'Posted account identity cannot change') END; END",
            "currency_update": "BEFORE UPDATE ON finance_currency WHEN EXISTS(SELECT 1 FROM finance_journal j WHERE j.currency_id=OLD.id) BEGIN SELECT CASE WHEN NEW.code<>OLD.code OR NEW.decimal_places<>OLD.decimal_places OR NEW.tenant_id<>OLD.tenant_id THEN RAISE(ABORT,'Posted currency cannot change') END; END",
            "period_update": "BEFORE UPDATE ON finance_accountingperiod WHEN EXISTS(SELECT 1 FROM finance_journal j WHERE j.period_id=OLD.id) BEGIN SELECT CASE WHEN NEW.starts_on<>OLD.starts_on OR NEW.ends_on<>OLD.ends_on OR NEW.tenant_id<>OLD.tenant_id THEN RAISE(ABORT,'Posted period dates cannot change') END; END",
        }
        for name, sql in statements.items():
            schema_editor.execute(f"CREATE TRIGGER finance_{name} {sql}")
    elif vendor == "postgresql":
        functions = {
            "journal": f"""IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Ledger deletion forbidden'; END IF;
                IF TG_OP='INSERT' THEN IF NEW.posted OR NOT ({header_valid}) THEN RAISE EXCEPTION 'Invalid journal header'; END IF;
                ELSE IF OLD.posted OR NOT NEW.posted OR NOT ({header_valid}) OR NOT ({balanced}) THEN RAISE EXCEPTION 'Immutable or unbalanced journal'; END IF; END IF; RETURN NEW;""",
            "line": f"""IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Ledger lines immutable'; END IF;
                PERFORM id FROM finance_journal WHERE id=NEW.journal_id FOR UPDATE;
                IF NOT ({line_valid}) THEN RAISE EXCEPTION 'Invalid or frozen ledger line'; END IF; RETURN NEW;""",
            "student": """IF TG_OP='INSERT' THEN IF NOT EXISTS(SELECT 1 FROM students_student s WHERE s.id=NEW.student_id AND s.tenant_id=NEW.tenant_id) THEN RAISE EXCEPTION 'Student tenant mismatch'; END IF;
                ELSE IF NEW.student_id<>OLD.student_id OR NEW.tenant_id<>OLD.tenant_id THEN RAISE EXCEPTION 'Financial identity cannot change'; END IF; END IF; RETURN NEW;""",
            "account": """IF EXISTS(SELECT 1 FROM finance_journalline l WHERE l.account_id=OLD.id) AND (NEW.code<>OLD.code OR NEW.kind<>OLD.kind OR NEW.purpose<>OLD.purpose OR NEW.tenant_id<>OLD.tenant_id) THEN RAISE EXCEPTION 'Posted account identity cannot change'; END IF; RETURN NEW;""",
            "currency": """IF EXISTS(SELECT 1 FROM finance_journal j WHERE j.currency_id=OLD.id) AND (NEW.code<>OLD.code OR NEW.decimal_places<>OLD.decimal_places OR NEW.tenant_id<>OLD.tenant_id) THEN RAISE EXCEPTION 'Posted currency cannot change'; END IF; RETURN NEW;""",
            "period": """IF EXISTS(SELECT 1 FROM finance_journal j WHERE j.period_id=OLD.id) AND (NEW.starts_on<>OLD.starts_on OR NEW.ends_on<>OLD.ends_on OR NEW.tenant_id<>OLD.tenant_id) THEN RAISE EXCEPTION 'Posted period dates cannot change'; END IF; RETURN NEW;""",
        }
        for name, body in functions.items():
            table = {"line": "journalline", "student": "studentaccount", "period": "accountingperiod"}.get(name, name)
            schema_editor.execute(f"CREATE FUNCTION finance_guard_{name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END; $$")
            events = "INSERT OR UPDATE OR DELETE" if name in ("journal", "line") else "INSERT OR UPDATE" if name == "student" else "UPDATE"
            schema_editor.execute(f"CREATE TRIGGER finance_{name}_guard BEFORE {events} ON finance_{table} FOR EACH ROW EXECUTE FUNCTION finance_guard_{name}()")
    else:
        raise RuntimeError("Finance ledger supports only SQLite and PostgreSQL.")


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]
    operations = [migrations.RunPython(install)]
