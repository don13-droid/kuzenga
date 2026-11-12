from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction

from apps.core.context import tenant_context
from apps.core.models import AuditEvent
from apps.finance.models import Account, AccountingPeriod, Currency, Journal, JournalLine
from apps.finance.services import balances, configure, post_journal, reverse_journal, student_account
from apps.students.models import Student
from apps.tenancy.models import Membership, Role
from tests.conftest import make_tenant, make_user


@pytest.fixture
def finance(db):
    tenant = make_tenant("finance", "professional")
    maker_user = make_user(tenant, Role.BURSAR)
    approver_user = make_user(tenant, Role.ADMIN)
    maker = Membership.objects.get(user=maker_user, tenant=tenant)
    approver = Membership.objects.get(user=approver_user, tenant=tenant)
    with tenant_context(tenant):
        usd = configure(Currency, {"code": "USD", "name": "US dollar"}, approver)
        zig = configure(Currency, {"code": "ZIG", "name": "ZiG"}, approver)
        period = configure(
            AccountingPeriod, {"name": "2026", "starts_on": date(2026, 1, 1), "ends_on": date(2026, 12, 31)}, approver
        )
        receivable = configure(
            Account, {"code": "1200", "name": "Student receivables", "kind": "asset", "purpose": "receivable"}, approver
        )
        income = configure(
            Account, {"code": "4000", "name": "Tuition", "kind": "income", "purpose": "tuition"}, approver
        )
        student = Student.objects.create(admission_number="A1", first_name="Ada", last_name="Test")
        account = student_account(student, maker)
    return {
        "tenant": tenant,
        "maker": maker,
        "approver": approver,
        "usd": usd,
        "zig": zig,
        "period": period,
        "receivable": receivable,
        "income": income,
        "student": account,
    }


def post(data, **overrides):
    values = dict(
        member=data["maker"],
        reference="J-001",
        idempotency_key="request-001",
        date=date(2026, 2, 1),
        period=data["period"],
        currency=data["usd"],
        description="Foundation test",
        source="manual",
        source_reference="APPROVED-TEST",
        lines=[
            {"account": data["receivable"], "student_account": data["student"], "debit": "100.10"},
            {"account": data["income"], "credit": "100.10"},
        ],
    )
    values.update(overrides)
    return post_journal(**values)


@pytest.mark.django_db
def test_balanced_post_replay_balance_and_audit(finance):
    with tenant_context(finance["tenant"]):
        journal = post(finance)
        assert journal.posted
        assert post(finance).pk == journal.pk
        assert Journal.objects.count() == 1
        assert balances(finance["maker"], finance["student"]) == {"USD": Decimal("100.10")}
        assert AuditEvent.objects.filter(action="finance.journal_posted").count() == 1
        with pytest.raises(ValidationError):
            post(finance, description="Different intent")


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", ["100.001", "NaN", "Infinity", "-1", 0.1, True])
def test_invalid_amounts_atomic(finance, invalid):
    with tenant_context(finance["tenant"]):
        with pytest.raises(ValidationError):
            post(
                finance,
                lines=[
                    {"account": finance["income"], "credit": invalid},
                    {"account": finance["receivable"], "student_account": finance["student"], "debit": "100.10"},
                ],
            )
        assert not Journal.objects.exists()
        assert not JournalLine.objects.exists()


@pytest.mark.django_db
def test_currency_separation_reversal_and_self_approval_denial(finance):
    with tenant_context(finance["tenant"]):
        first = post(finance)
        post(finance, reference="J-002", idempotency_key="request-002", currency=finance["zig"])
        assert balances(finance["maker"], finance["student"]) == {"USD": Decimal("100.10"), "ZIG": Decimal("100.10")}
        with pytest.raises(PermissionDenied):
            reverse_journal(
                first,
                member=finance["maker"],
                reference="R-1",
                idempotency_key="reverse-1",
                date=date(2026, 2, 2),
                period=finance["period"],
                reason="Incorrect charge",
            )
        reverse_journal(
            first,
            member=finance["approver"],
            reference="R-1",
            idempotency_key="reverse-1",
            date=date(2026, 2, 2),
            period=finance["period"],
            reason="Incorrect charge",
        )
        assert balances(finance["maker"], finance["student"])["USD"] == 0
        assert Journal.objects.get(pk=first.pk).posted
        with pytest.raises(ValidationError):
            reverse_journal(
                first,
                member=finance["approver"],
                reference="R-2",
                idempotency_key="reverse-2",
                date=date(2026, 2, 2),
                period=finance["period"],
                reason="Second reversal",
            )


@pytest.mark.django_db
def test_tenant_and_permission_boundaries(finance, tenant_b, teacher_a):
    with tenant_context(tenant_b):
        assert not Journal.objects.exists()
        with pytest.raises(PermissionDenied):
            post(finance)
    with tenant_context(finance["tenant"]):
        foreign = Currency(tenant=tenant_b, code="USD", name="Foreign")
        # Save outside this context using the other school's trusted context.
    with tenant_context(tenant_b):
        foreign.save()
    with tenant_context(finance["tenant"]):
        with pytest.raises(ValidationError):
            post(finance, currency=foreign)
        with pytest.raises(PermissionDenied):
            configure(Account, {"code": "1", "name": "No", "kind": "asset"}, finance["maker"])


@pytest.mark.django_db
def test_orm_and_raw_sql_immutability(finance):
    with tenant_context(finance["tenant"]):
        journal = post(finance)
        with pytest.raises(ValidationError):
            journal.save()
        with pytest.raises(ValidationError):
            Journal.objects.filter(pk=journal.pk).update(description="Tampered")
        for sql in [
            "UPDATE finance_journal SET description='Tampered' WHERE id=%s",
            "DELETE FROM finance_journal WHERE id=%s",
        ]:
            with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql, [journal.pk.hex])
        line = journal.lines.first()
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE finance_journalline SET debit=1 WHERE id=%s", [line.pk.hex])


@pytest.mark.django_db
def test_closed_period_and_unbalanced_journal(finance):
    with tenant_context(finance["tenant"]):
        with pytest.raises(ValidationError):
            post(
                finance,
                lines=[
                    {"account": finance["income"], "credit": "1"},
                    {"account": finance["receivable"], "student_account": finance["student"], "debit": "2"},
                ],
            )
        finance["period"].closed = True
        finance["period"].save()
        with pytest.raises(ValidationError):
            post(finance)


@pytest.mark.django_db
def test_decimal_fraction_balance_in_database(finance):
    with tenant_context(finance["tenant"]):
        journal = post(
            finance,
            lines=[
                {"account": finance["receivable"], "student_account": finance["student"], "debit": "0.10"},
                {"account": finance["receivable"], "student_account": finance["student"], "debit": "0.20"},
                {"account": finance["income"], "credit": "0.30"},
            ],
        )
        assert journal.posted


@pytest.mark.django_db
def test_foundation_pages_and_tenant_denials(client, finance, admin_b):
    client.force_login(finance["approver"].user)
    for url in [
        "/finance/",
        "/finance/accounts/",
        "/finance/ledger/",
        "/finance/audit/",
        "/finance/settings/currencies/",
        "/finance/settings/accounts/",
        "/finance/settings/periods/",
    ]:
        assert client.get(url).status_code == 200, url
    assert client.get("/finance/ledger/?start=invalid").status_code == 200
    client.force_login(finance["maker"].user)
    assert client.get("/finance/journals/new/").status_code == 200
    assert client.get("/finance/settings/accounts/").status_code == 403
    with tenant_context(finance["tenant"]):
        entry = post(finance)
    assert client.get(f"/finance/journals/{entry.pk}/").status_code == 200
    client.force_login(admin_b)
    assert client.get(f"/finance/journals/{entry.pk}/").status_code == 403  # No finance entitlement.


@pytest.mark.django_db
def test_same_person_cannot_reverse_even_with_owner_permission(finance):
    with tenant_context(finance["tenant"]):
        entry = post(finance)
        Membership.objects.filter(pk=finance["maker"].pk).update(role=Role.OWNER)
        with pytest.raises(PermissionDenied):
            reverse_journal(
                entry,
                member=finance["maker"],
                reference="R-1",
                idempotency_key="reverse-1",
                date=date(2026, 2, 2),
                period=finance["period"],
                reason="Wrong entry",
            )


@pytest.mark.django_db
def test_platform_superuser_has_no_automatic_finance_access(finance):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_superuser("platform-finance@example.test", "unused-test-password")
    membership = Membership.objects.create(user=user, tenant=finance["tenant"], role=Role.OWNER)
    with tenant_context(finance["tenant"]), pytest.raises(PermissionDenied):
        post(finance, member=membership)


@pytest.mark.django_db
def test_raw_sql_unbalanced_post_and_append_rejected(finance):
    from apps.finance.models import _ledger_write

    with tenant_context(finance["tenant"]):
        marker = _ledger_write.set(True)
        try:
            with pytest.raises(DatabaseError), transaction.atomic():
                draft = Journal.objects.create(
                    reference="UNBALANCED",
                    idempotency_key="bad",
                    fingerprint="0" * 64,
                    date=date(2026, 2, 1),
                    period=finance["period"],
                    currency=finance["usd"],
                    description="Invalid journal",
                    source="test",
                    source_reference="TEST",
                    created_by=finance["maker"],
                )
                JournalLine.objects.create(journal=draft, account=finance["income"], credit=1)
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE finance_journal SET posted=TRUE WHERE id=%s", [draft.pk.hex])
        finally:
            _ledger_write.reset(marker)
        assert not Journal.objects.exists()
        entry = post(finance)
        first = entry.lines.first()
        import uuid

        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO finance_journalline(id,created_at,updated_at,debit,credit,description,tenant_id,account_id,journal_id,student_account_id) SELECT %s,created_at,updated_at,debit,credit,description,tenant_id,account_id,journal_id,student_account_id FROM finance_journalline WHERE id=%s",
                [uuid.uuid4().hex, first.pk.hex],
            )


@pytest.mark.django_db
def test_finance_cross_tenant_reference_hidden(client, finance):
    second = make_tenant("other-finance", "professional")
    user = make_user(second, Role.BURSAR)
    with tenant_context(finance["tenant"]):
        entry = post(finance)
    client.force_login(user)
    assert client.get(f"/finance/journals/{entry.pk}/").status_code == 404


@pytest.mark.django_db
def test_exchange_metadata_and_account_identity_preserved(finance):
    with tenant_context(finance["tenant"]):
        entry = post(
            finance,
            exchange_rate=Decimal("25.1234567890"),
            rate_effective_date=date(2026, 2, 1),
            rate_reference="School approved quote",
        )
        assert entry.exchange_rate == Decimal("25.1234567890")
        finance["receivable"].kind = "income"
        with pytest.raises(ValidationError):
            finance["receivable"].save()
        finance["usd"].decimal_places = 4
        with pytest.raises(ValidationError):
            finance["usd"].save()


@pytest.mark.django_db
def test_journal_form_post_and_request_time_choices(client, finance):
    from apps.finance.forms import JournalForm, JournalLineForm

    with tenant_context(finance["tenant"]):
        cash = configure(
            Account, {"code": "1000", "name": "Cash", "kind": "asset", "purpose": "cash"}, finance["approver"]
        )
        assert JournalForm().fields["currency"].queryset.filter(pk=finance["usd"].pk).exists()
        assert JournalLineForm().fields["account"].queryset.filter(pk=cash.pk).exists()
    client.force_login(finance["maker"].user)
    data = {
        "reference": "WEB-1",
        "idempotency_key": "web-1",
        "date": "2026-02-01",
        "period": str(finance["period"].pk),
        "currency": str(finance["usd"].pk),
        "description": "Recorded income",
        "source_reference": "APPROVED-1",
        "form-TOTAL_FORMS": "2",
        "form-INITIAL_FORMS": "0",
        "form-0-account": str(cash.pk),
        "form-0-debit": "1.25",
        "form-1-account": str(finance["income"].pk),
        "form-1-credit": "1.25",
    }
    response = client.post("/finance/journals/new/", data)
    assert response.status_code == 302
    assert client.post("/finance/journals/new/", data).status_code == 302
    with tenant_context(finance["tenant"]):
        assert Journal.objects.filter(reference="WEB-1", posted=True).count() == 1
