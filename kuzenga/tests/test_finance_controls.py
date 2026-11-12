# ruff: noqa: F811
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.context import tenant_context
from apps.finance.controls import decide_control, disburse_refund, request_control
from apps.finance.models import Account, FinanceDecision, FinanceRequest, Journal, RefundDisbursement
from apps.finance.services import balances, configure
from apps.finance.workflows import confirm_payment, invoice_outstanding
from tests.test_finance_foundation import finance  # noqa: F401
from tests.test_finance_workflows import bill, core, pay  # noqa: F401


def request(core, **changes):
    invoice = bill(core)[0]
    contra = Account.objects.filter(code="CONTRA").first() or configure(
        Account,
        {"code": "CONTRA", "name": "Scholarships and discounts", "kind": "income", "purpose": "concession"},
        core["approver"],
    )
    values = dict(
        member=core["maker"],
        kind="scholarship",
        invoice=invoice,
        counter_account=contra,
        mode="percentage",
        value=Decimal("10"),
        benefit_code="SCHOLAR-2026",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        eligibility="Eligibility reviewed against the private school policy record",
        reason="Approved scholarship application requested",
        supporting_reference="POLICY-1",
        idempotency_key="scholar-1",
    )
    values.update(changes)
    return request_control(**values)


def approve(core, req, **changes):
    values = dict(
        member=core["approver"],
        request=req,
        approved=True,
        reason="Eligibility and policy checked",
        on_date=date(2026, 2, 2),
        period=core["period"],
    )
    values.update(changes)
    return decide_control(**values)


@pytest.mark.django_db
def test_percentage_scholarship_balances_ledger_and_duplicate(core):
    with tenant_context(core["tenant"]):
        req = request(core)
        assert request(core).pk == req.pk
        assert invoice_outstanding(req.invoice) == 150
        decision = approve(core, req)
        assert decision.amount == 15
        assert invoice_outstanding(req.invoice) == 135
        assert balances(core["maker"], core["student"])["USD"] == 135
        assert approve(core, req).pk == decision.pk
        with pytest.raises(ValidationError):
            request(core, idempotency_key="different-submit")
        assert FinanceRequest.objects.count() == 1
        for journal in Journal.objects.all():
            assert sum(journal.lines.values_list("debit", flat=True)) == sum(
                journal.lines.values_list("credit", flat=True)
            )


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["discount", "bursary", "sibling", "staff_child", "waiver"])
def test_fixed_concession_types(core, kind):
    with tenant_context(core["tenant"]):
        req = request(core, kind=kind, mode="fixed", value="25.00")
        approve(core, req)
        assert invoice_outstanding(req.invoice) == 125


@pytest.mark.django_db
def test_unauthorised_duplicate_excess_and_effective_period(core, tenant_b):
    with tenant_context(core["tenant"]):
        req = request(core)
        from apps.tenancy.models import Membership, Role

        Membership.objects.filter(pk=core["maker"].pk).update(role=Role.OWNER)
        with pytest.raises(PermissionDenied):
            approve(core, req, member=core["maker"])
        with pytest.raises(ValidationError):
            approve(core, req, on_date=date(2027, 1, 1))
        with pytest.raises(ValidationError):
            request(core, value="101")
        rejected = approve(core, req, approved=False, reason="Not eligible")
        assert not rejected.journal_id
        assert invoice_outstanding(req.invoice) == 150
        too_large = request(core, mode="fixed", value="151", benefit_code="EXCESS", idempotency_key="excess")
        with pytest.raises(ValidationError):
            approve(core, too_large)
    with tenant_context(tenant_b), pytest.raises(PermissionDenied):
        approve(core, req)


@pytest.mark.django_db
def test_refund_approval_is_not_disbursement_and_currency_separation(core):
    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        payment = pay(core, value="200")
        confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        assert invoice_outstanding(invoice) == 0
        req = request_control(
            member=core["maker"],
            kind="refund",
            payment=payment,
            student_account=core["student"],
            currency=core["usd"],
            receivable_account=core["receivable"],
            counter_account=core["cash"],
            mode="fixed",
            value="50",
            benefit_code="REFUND1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
            eligibility="Student account overpayment",
            reason="Return excess payment",
            supporting_reference=payment.number,
            idempotency_key="refund1",
        )
        decision = approve(core, req)
        assert decision.approved and not decision.journal_id
        assert not RefundDisbursement.objects.exists()
        assert balances(core["maker"], core["student"])["USD"] == -50
        from apps.tenancy.models import Membership, Role

        Membership.objects.filter(pk=core["approver"].pk).update(role=Role.OWNER)
        with pytest.raises(PermissionDenied):
            disburse_refund(
                member=core["approver"],
                request=req,
                on_date=date(2026, 2, 3),
                period=core["period"],
                reference="CASH-OUT1",
            )
        paid = disburse_refund(
            member=core["maker"], request=req, on_date=date(2026, 2, 3), period=core["period"], reference="CASH-OUT1"
        )
        assert (
            disburse_refund(
                member=core["maker"],
                request=req,
                on_date=date(2026, 2, 3),
                period=core["period"],
                reference="CASH-OUT1",
            ).pk
            == paid.pk
        )
        assert balances(core["maker"], core["student"])["USD"] == 0
        assert FinanceDecision.objects.count() == 1
        with pytest.raises(ValidationError):
            request_control(
                member=core["maker"],
                kind="refund",
                payment=payment,
                currency=core["zig"],
                counter_account=core["cash"],
                mode="fixed",
                value="1",
                benefit_code="CROSS-CURRENCY",
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
                eligibility="Invalid source currency",
                reason="Should be rejected",
                supporting_reference=payment.number,
                idempotency_key="cross-currency",
            )
        from apps.finance.controls import close_refund
        from apps.tenancy.models import Membership, Role
        from tests.conftest import make_user

        reviewer = make_user(core["tenant"], Role.OWNER, email="refund-reviewer@finance.test")
        member = Membership.objects.get(user=reviewer, tenant=core["tenant"])
        closed = close_refund(
            member=member,
            request=req,
            on_date=date(2026, 2, 4),
            period=core["period"],
            reason="Disbursement correction independently verified",
        )
        assert closed.journal.reversal_of_id == paid.journal_id
        assert balances(core["maker"], core["student"])["USD"] == -50
        assert (
            close_refund(member=member, request=req, on_date=date(2026, 2, 4), period=core["period"], reason="Retry").pk
            == closed.pk
        )


@pytest.mark.django_db
def test_credit_debit_writeoff_and_separate_reversal(core):
    from apps.finance.controls import reverse_control
    from apps.tenancy.models import Membership, Role
    from tests.conftest import make_user

    with tenant_context(core["tenant"]):
        credit = request(
            core, kind="credit", mode="fixed", value="20", benefit_code="CREDIT1", idempotency_key="credit1"
        )
        approve(core, credit)
        debit = request(core, kind="debit", mode="fixed", value="30", benefit_code="DEBIT1", idempotency_key="debit1")
        approve(core, debit)
        bad = configure(
            Account, {"code": "BAD", "name": "Bad debt", "kind": "expense", "purpose": "bad_debt"}, core["approver"]
        )
        writeoff = request(
            core,
            kind="write_off",
            mode="fixed",
            value="10",
            counter_account=bad,
            benefit_code="WRITE1",
            idempotency_key="write1",
        )
        approve(core, writeoff)
        assert invoice_outstanding(credit.invoice) == 150
        with pytest.raises(PermissionDenied):
            reverse_control(
                member=core["approver"],
                request=credit,
                on_date=date(2026, 2, 3),
                period=core["period"],
                reason="Correction",
            )
        reviewer = make_user(core["tenant"], Role.OWNER)
        member = Membership.objects.get(user=reviewer, tenant=core["tenant"])
        reverse_control(
            member=member,
            request=credit,
            on_date=date(2026, 2, 3),
            period=core["period"],
            reason="Correction checked independently",
        )
        assert invoice_outstanding(credit.invoice) == 170
        assert balances(core["maker"], core["student"])["USD"] == 170


@pytest.mark.django_db
def test_debit_adjustment_allocation_above_original_invoice(core):
    with tenant_context(core["tenant"]):
        debit = request(core, kind="debit", mode="fixed", value="100", benefit_code="DEBIT", idempotency_key="debit")
        approve(core, debit)
        payment = pay(core, value="250")
        confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        assert invoice_outstanding(debit.invoice) == 0
        assert balances(core["maker"], core["student"])["USD"] == 0


@pytest.mark.django_db
def test_concession_school_pages_and_approval_separation(client, core):
    with tenant_context(core["tenant"]):
        req = request(core)
    client.force_login(core["maker"].user)
    for url in ["/finance/controls/", "/finance/controls/new/", f"/finance/controls/{req.pk}/"]:
        assert client.get(url).status_code == 200
    data = {"approved": "yes", "on_date": "2026-02-02", "period": str(core["period"].pk), "reason": "Policy verified"}
    assert client.post(f"/finance/controls/{req.pk}/decide/", data).status_code == 403
    client.force_login(core["approver"].user)
    assert client.post(f"/finance/controls/{req.pk}/decide/", data).status_code == 302
    with tenant_context(core["tenant"]):
        assert invoice_outstanding(req.invoice) == 135


@pytest.mark.django_db
def test_unused_refund_cancellation_releases_allocation_reservation(core):
    from apps.finance.controls import close_refund
    from apps.finance.models import FeeRule
    from apps.finance.workflows import allocate_payment, bill_students
    from apps.tenancy.models import Membership, Role
    from tests.conftest import make_user

    with tenant_context(core["tenant"]):
        bill(core)
        payment = pay(core, value="200")
        confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        refund = request_control(
            member=core["maker"],
            kind="refund",
            payment=payment,
            counter_account=core["cash"],
            mode="fixed",
            value="50",
            benefit_code="RESERVE",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
            eligibility="Unallocated overpayment",
            reason="Refund requested",
            supporting_reference=payment.number,
            idempotency_key="reserve",
        )
        approve(core, refund)
        fee = configure(
            FeeRule,
            dict(
                code="EXTRA",
                name="Additional charge",
                academic_year=core["class"].academic_year,
                currency=core["usd"],
                amount=Decimal("50"),
                income_account=core["income"],
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
                due_date=date(2026, 2, 28),
            ),
            core["maker"],
        )
        invoice = bill_students(
            member=core["maker"],
            fee=fee,
            on_date=date(2026, 2, 2),
            period=core["period"],
            receivable_account=core["receivable"],
        )[0]
        with pytest.raises(ValidationError):
            allocate_payment(member=core["maker"], payment=payment, invoice=invoice, value="50")
        reviewer = make_user(core["tenant"], Role.OWNER, email="cancel-reviewer@finance.test")
        member = Membership.objects.get(user=reviewer, tenant=core["tenant"])
        count = Journal.objects.count()
        cancelled = close_refund(
            member=member,
            request=refund,
            on_date=date(2026, 2, 3),
            period=core["period"],
            reason="Refund no longer required; independently authorised",
        )
        assert not cancelled.journal_id
        assert Journal.objects.count() == count
        allocate_payment(member=core["maker"], payment=payment, invoice=invoice, value="50")
        assert invoice_outstanding(invoice) == 0
