# ruff: noqa: F811
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.context import tenant_context
from apps.finance.models import Account, FeeRule, Invoice, Journal, PaymentAllocation, Receipt
from apps.finance.services import balances, configure
from apps.finance.workflows import (
    allocate_payment,
    arrange_payment,
    arrangement_status,
    bill_students,
    confirm_payment,
    debt_rows,
    follow_up,
    invoice_outstanding,
    invoice_paid,
    payment_state,
    record_payment,
    reverse_payment,
)
from apps.students.models import StudentEnrolment
from tests.conftest import make_class
from tests.test_finance_foundation import finance  # noqa: F401


@pytest.fixture
def core(finance):
    with tenant_context(finance["tenant"]):
        classroom = make_class(finance["tenant"])
        StudentEnrolment.objects.create(
            student=finance["student"].student, class_group=classroom, effective_from=date(2026, 1, 1)
        )
        fee = configure(
            FeeRule,
            dict(
                code="TUITION",
                name="Tuition",
                academic_year=classroom.academic_year,
                currency=finance["usd"],
                amount=Decimal("150"),
                income_account=finance["income"],
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
                due_date=date(2026, 2, 15),
            ),
            finance["maker"],
        )
        cash = configure(
            Account, {"code": "1000", "name": "Cash", "kind": "asset", "purpose": "cash"}, finance["approver"]
        )
        mobile = configure(
            Account,
            {"code": "1100", "name": "Mobile clearing", "kind": "asset", "purpose": "mobile_clearing"},
            finance["approver"],
        )
    return {**finance, "fee": fee, "cash": cash, "mobile": mobile, "class": classroom}


def bill(core, **kwargs):
    return bill_students(
        member=core["maker"],
        fee=core["fee"],
        on_date=date(2026, 2, 1),
        period=core["period"],
        receivable_account=core["receivable"],
        **kwargs,
    )


def pay(core, value="50", key="payment1", **kwargs):
    data = dict(
        member=core["maker"],
        student=core["student"],
        currency=core["usd"],
        value=value,
        method="cash",
        receiving_account=core["cash"],
        receivable_account=core["receivable"],
        on_date=date(2026, 2, 2),
        idempotency_key=key,
    )
    data.update(kwargs)
    return record_payment(**data)


@pytest.mark.django_db
def test_requested_150_50_100_reversal_workflow(core):
    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        assert invoice.amount == 150
        assert bill(core)[0].pk == invoice.pk
        assert Invoice.objects.count() == 1
        payment = pay(core)
        assert payment_state(payment) == "pending"
        assert balances(core["maker"], core["student"])["USD"] == 150
        receipt = confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        assert receipt.number.startswith("RCPT-")
        assert invoice_paid(invoice) == 50
        assert invoice_outstanding(invoice) == 100
        assert balances(core["maker"], core["student"])["USD"] == 100
        second = pay(core, value="100", key="second")
        confirm_payment(member=core["maker"], payment=second, period=core["period"])
        assert invoice_outstanding(invoice) == 0
        assert balances(core["maker"], core["student"])["USD"] == 0
        with pytest.raises(PermissionDenied):
            reverse_payment(
                member=core["maker"],
                payment=payment,
                period=core["period"],
                on_date=date(2026, 2, 3),
                reason="Wrong payment",
            )
        reverse_payment(
            member=core["approver"],
            payment=payment,
            period=core["period"],
            on_date=date(2026, 2, 3),
            reason="Wrong payment",
        )
        assert invoice_outstanding(invoice) == 50
        assert balances(core["maker"], core["student"])["USD"] == 50
        assert payment_state(payment) == "reversed"
        from apps.finance.student_accounts import statement

        assert statement(core["maker"], core["student"], core["usd"])["closing"] == 50
        assert debt_rows(core["maker"], on_date=date(2026, 2, 1))[0]["outstanding"] == 150
        assert Receipt.objects.filter(pk=receipt.pk).exists()
        assert PaymentAllocation.objects.count() == 2
        for journal in Journal.objects.filter(posted=True):
            assert sum(journal.lines.values_list("debit", flat=True)) == sum(
                journal.lines.values_list("credit", flat=True)
            )


@pytest.mark.django_db
def test_duplicate_confirmation_overpayment_and_currency(core):
    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        payment = pay(core, value="200")
        assert pay(core, value="200").pk == payment.pk
        with pytest.raises(ValidationError):
            pay(core, value="201")
        first = confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        assert confirm_payment(member=core["maker"], payment=payment, period=core["period"]).pk == first.pk
        assert invoice_outstanding(invoice) == 0
        assert balances(core["maker"], core["student"])["USD"] == -50
        zig = pay(core, key="zig", currency=core["zig"])
        confirm_payment(member=core["maker"], payment=zig, period=core["period"])
        with pytest.raises(ValidationError):
            allocate_payment(member=core["maker"], payment=zig, invoice=invoice, value="1")
        assert Receipt.objects.count() == 2


@pytest.mark.django_db
def test_mobile_requires_verification_and_provider_duplicate_denied(core):
    with tenant_context(core["tenant"]):
        payment = pay(core, method="ecocash", receiving_account=core["mobile"], external_reference="txn123")
        with pytest.raises(ValidationError):
            confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        with pytest.raises(ValidationError):
            pay(
                core, key="retry-other", method="ecocash", receiving_account=core["mobile"], external_reference="TXN123"
            )
        assert not Journal.objects.exists()
        confirm_payment(
            member=core["maker"],
            payment=payment,
            period=core["period"],
            verified=True,
            verification_reference="Bank reconciliation evidence 1",
        )
        assert payment_state(payment) == "confirmed"


@pytest.mark.django_db
def test_ageing_arrangement_followups_and_tenant_denial(core, tenant_b):
    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        assert debt_rows(core["maker"], on_date=date(2026, 2, 10))[0]["bucket"] == "Current"
        assert debt_rows(core["maker"], on_date=date(2026, 3, 1))[0]["bucket"] == "1–30 days"
        arrangement = arrange_payment(
            member=core["maker"],
            invoice=invoice,
            schedule=[{"due": "2026-03-01", "amount": "150"}],
            reason="Family agreement",
            idempotency_key="plan",
        )
        assert arrangement_status(arrangement, date(2026, 3, 2)) == "missed instalment"
        note = follow_up(member=core["maker"], invoice=invoice, note="Meeting agreed", idempotency_key="follow")
        assert (
            follow_up(member=core["maker"], invoice=invoice, note="Meeting agreed", idempotency_key="follow").pk
            == note.pk
        )
    with tenant_context(tenant_b), pytest.raises(PermissionDenied):
        bill(core)


@pytest.mark.django_db
def test_school_billing_payment_receipt_pdf_and_debt_pages(client, core):
    client.force_login(core["maker"].user)
    data = {
        "fee": str(core["fee"].pk),
        "date": "2026-02-01",
        "period": str(core["period"].pk),
        "receivable_account": str(core["receivable"].pk),
        "students": [str(core["student"].student_id)],
        "action": "preview",
    }
    preview = client.post("/finance/billing/", data)
    assert preview.status_code == 200
    token = preview.context["preview_token"]
    assert token
    assert client.post("/finance/billing/", {"action": "post", "preview_token": token}).status_code == 302
    assert client.post("/finance/billing/", {"action": "post", "preview_token": token}).status_code == 302
    with tenant_context(core["tenant"]):
        assert Invoice.objects.count() == 1
        payment = pay(core)
    response = client.post(
        f"/finance/payments/{payment.pk}/",
        {"action": "confirm", "period": str(core["period"].pk), "auto_allocate": "on"},
    )
    assert response.status_code == 302
    with tenant_context(core["tenant"]):
        receipt = Receipt.objects.get()
        invoice = Invoice.objects.get()
    for url in [
        "/finance/invoices/",
        f"/finance/invoices/{invoice.pk}/",
        "/finance/payments/",
        "/finance/payments/new/",
        f"/finance/payments/{payment.pk}/",
        "/finance/receipts/",
        f"/finance/receipts/{receipt.pk}/",
        "/finance/debt/",
        "/finance/arrangements/new/",
        "/finance/follow-ups/new/",
        "/finance/collections/",
    ]:
        assert client.get(url).status_code == 200, url
    pdf = client.get(f"/finance/receipts/{receipt.pk}/print.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")
    assert pdf["Cache-Control"] == "private, no-store"
    assert (
        client.post(
            f"/finance/payments/{payment.pk}/reverse/",
            {"period": str(core["period"].pk), "on_date": "2026-02-03", "reason": "Wrong payment"},
        ).status_code
        == 403
    )
    client.force_login(core["approver"].user)
    assert (
        client.post(
            f"/finance/payments/{payment.pk}/reverse/",
            {"period": str(core["period"].pk), "on_date": "2026-02-03", "reason": "Wrong payment"},
        ).status_code
        == 302
    )
    assert b"VOID" in client.get(f"/finance/receipts/{receipt.pk}/").content


@pytest.mark.django_db
def test_core_cross_tenant_urls_and_raw_document_protection(client, core):
    from django.db import DatabaseError, connection, transaction

    from apps.tenancy.models import Role
    from tests.conftest import make_tenant, make_user

    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        payment = pay(core)
        receipt = confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE finance_invoice SET amount=1 WHERE id=%s", [invoice.pk.hex])
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM finance_receipt WHERE id=%s", [receipt.pk.hex])
    other = make_tenant("other-core", "professional")
    user = make_user(other, Role.BURSAR)
    client.force_login(user)
    for url in [
        f"/finance/invoices/{invoice.pk}/",
        f"/finance/payments/{payment.pk}/",
        f"/finance/receipts/{receipt.pk}/",
        f"/finance/receipts/{receipt.pk}/print.pdf",
    ]:
        assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_bulk_billing_and_manual_partial_allocations(core):
    from apps.finance.services import student_account
    from apps.students.models import Student

    with tenant_context(core["tenant"]):
        second = Student.objects.create(admission_number="B2", first_name="Second", last_name="Learner")
        StudentEnrolment.objects.create(student=second, class_group=core["class"], effective_from=date(2026, 1, 1))
        second_account = student_account(second, core["maker"])
        invoices = bill(core)
        assert len(invoices) == 2
        assert len(bill(core)) == 2
        assert Invoice.objects.count() == 2
        own = next(i for i in invoices if i.student_account_id == core["student"].pk)
        other = next(i for i in invoices if i.student_account_id == second_account.pk)
        payment = pay(core, value="50")
        confirm_payment(member=core["maker"], payment=payment, period=core["period"], auto_allocate=False)
        assert invoice_paid(own) == 0
        with pytest.raises(ValidationError):
            allocate_payment(member=core["maker"], payment=payment, invoice=other, value="50")
        with pytest.raises(ValidationError):
            allocate_payment(member=core["maker"], payment=payment, invoice=own, value="51")
        allocation = allocate_payment(member=core["maker"], payment=payment, invoice=own, value="50")
        assert allocate_payment(member=core["maker"], payment=payment, invoice=own, value="50").pk == allocation.pk
        assert invoice_outstanding(own) == 100
        assert invoice_outstanding(other) == 150


@pytest.mark.django_db
def test_rejected_payment_and_controlled_arrangement_amendment(core):
    from apps.finance.workflows import reject_payment

    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        payment = pay(core)
        reject_payment(member=core["maker"], payment=payment, reason="Bank transaction not found")
        assert payment_state(payment) == "rejected"
        with pytest.raises(ValidationError):
            confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        assert not Receipt.objects.exists()
        first = arrange_payment(
            member=core["maker"],
            invoice=invoice,
            schedule=[{"due": "2026-03-01", "amount": "150"}],
            reason="Agreed plan",
            idempotency_key="plan1",
        )
        second = arrange_payment(
            member=core["approver"],
            invoice=invoice,
            supersedes=first,
            schedule=[{"due": "2026-04-01", "amount": "50"}, {"due": "2026-05-01", "amount": "100"}],
            reason="Approved extension",
            idempotency_key="plan2",
        )
        assert second.supersedes_id == first.pk
        assert arrangement_status(first) == "superseded"
        assert len(first.schedule) == 1
        assert invoice_outstanding(invoice) == 150
