# ruff: noqa: F811
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.context import tenant_context
from apps.finance.models import Account, OpeningEntry, ReconciledEntry, StatementRow
from apps.finance.operations import (
    cash_expected,
    decide_import,
    decide_match,
    open_cash,
    preview_import,
    request_match,
    review_cash,
    submit_cash,
)
from apps.finance.services import balances, configure
from apps.finance.workflows import confirm_payment, payment_state
from tests.test_finance_foundation import finance  # noqa: F401
from tests.test_finance_workflows import bill, core, pay  # noqa: F401


@pytest.mark.django_db
def test_cash_up_shortage_overage_immutability_and_closing(core):
    with tenant_context(core["tenant"]):
        bill(core)
        session = open_cash(
            member=core["maker"],
            on_date=date(2026, 2, 2),
            currency=core["usd"],
            account=core["cash"],
            opening_float="10",
        )
        payment = pay(core)
        confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        assert cash_expected(session) == 60
        submission = submit_cash(
            member=core["maker"], session=session, actual="55", note="Five dollars short; investigated"
        )
        assert submission.difference == -5
        from apps.tenancy.models import Membership, Role

        Membership.objects.filter(pk=core["maker"].pk).update(role=Role.OWNER)
        with pytest.raises(PermissionDenied):
            review_cash(member=core["maker"], submission=submission, approved=True, reason="Self approval denied")
        with pytest.raises(ValidationError):
            submit_cash(member=core["maker"], session=session, actual="56", note="Change count")
        review = review_cash(
            member=core["approver"], submission=submission, approved=True, reason="Difference retained and investigated"
        )
        assert review.approved
        later = pay(core, key="late")
        with pytest.raises(ValidationError):
            confirm_payment(member=core["maker"], payment=later, period=core["period"])
        second = open_cash(
            member=core["maker"],
            on_date=date(2026, 2, 3),
            currency=core["usd"],
            account=core["cash"],
            opening_float="10",
        )
        over = submit_cash(member=core["maker"], session=second, actual="15", note="Five dollar overage")
        assert over.difference == 5
        fractions = open_cash(
            member=core["maker"],
            on_date=date(2026, 2, 4),
            currency=core["usd"],
            account=core["cash"],
            opening_float="0.30",
        )
        small = submit_cash(member=core["maker"], session=fractions, actual="0.10", note="Twenty cents short")
        assert small.difference == Decimal("-0.20")


@pytest.mark.django_db
def test_statement_import_duplicates_manual_match_and_tenant(core, tenant_b, client):
    with tenant_context(core["tenant"]):
        bank = configure(
            Account, {"code": "BANK", "name": "Bank", "kind": "asset", "purpose": "bank"}, core["approver"]
        )
        payment = pay(core, method="bank_transfer", receiving_account=bank, external_reference="BANK001")
        assert payment_state(payment) == "pending"
        source = "date,reference,amount,currency\n2026-02-02,BANK001,50.00,USD\n"
        batch = preview_import(
            member=core["maker"],
            kind="statement",
            source=source,
            source_name="bank.csv",
            account=bank,
            currency=core["usd"],
        )
        assert (
            preview_import(
                member=core["maker"],
                kind="statement",
                source=source,
                source_name="again.csv",
                account=bank,
                currency=core["usd"],
            ).pk
            == batch.pk
        )
        assert not StatementRow.objects.exists()
        decide_import(member=core["approver"], batch=batch, approved=True, reason="Statement source reviewed")
        assert payment_state(payment) == "pending"  # Importing a statement is not payment confirmation.
        confirm_payment(
            member=core["maker"],
            payment=payment,
            period=core["period"],
            verified=True,
            verification_reference="BANK001 evidence",
        )
        line = payment.decision.journal.lines.get(account=bank)
        match = request_match(
            member=core["maker"],
            row=StatementRow.objects.get(),
            line=line,
            reason="Reference and amount verified",
            idempotency_key="match1",
        )
        with pytest.raises(PermissionDenied):
            decide_match(member=core["maker"], match=match, approved=True, reason="Self approval")
        decide_match(member=core["approver"], match=match, approved=True, reason="Independent check")
        assert ReconciledEntry.objects.count() == 1
        duplicate = preview_import(
            member=core["maker"],
            kind="statement",
            source=source.replace("50.00", "50"),
            source_name="overlap.csv",
            account=bank,
            currency=core["usd"],
        )
        assert duplicate.errors
        with pytest.raises(ValidationError):
            decide_import(member=core["approver"], batch=duplicate, approved=True, reason="Try duplicate")
    with tenant_context(tenant_b), pytest.raises(PermissionDenied):
        request_match(member=core["maker"], row=match.row, line=line, reason="Cross school", idempotency_key="cross")
    from apps.tenancy.models import Role
    from tests.conftest import make_tenant, make_user

    other = make_tenant("reconcile-other", "professional")
    user = make_user(other, Role.ADMIN)
    client.force_login(user)
    assert client.get(f"/finance/reconciliation/{match.pk}/review/").status_code == 404


@pytest.mark.django_db
def test_opening_import_currency_duplicate_and_unknown_student(core, client):
    with tenant_context(core["tenant"]):
        opening = configure(
            Account, {"code": "OPEN", "name": "Opening funds", "kind": "equity", "purpose": "opening"}, core["approver"]
        )
        source = "student_reference,currency,amount,reference\nA1,USD,100.00,LEGACY-1\nA1,ZIG,-20.00,LEGACY-2\n"
        batch = preview_import(
            member=core["maker"],
            kind="opening",
            source=source,
            source_name="legacy.csv",
            receivable=core["receivable"],
            offset=opening,
        )
        assert not batch.errors
        assert not OpeningEntry.objects.exists()
        client.force_login(core["maker"].user)
        preview = client.get(f"/finance/imports/{batch.pk}/")
        assert preview.status_code == 200
        assert b"Projected after addition" in preview.content
        decision = decide_import(
            member=core["approver"],
            batch=batch,
            approved=True,
            reason="Legacy balances reconciled",
            period=core["period"],
            on_date=date(2026, 1, 1),
        )
        assert decision.approved
        reviewed = client.get(f"/finance/imports/{batch.pk}/")
        assert reviewed.status_code == 200
        assert b"Projected after addition" not in reviewed.content
        assert balances(core["maker"], core["student"]) == {"USD": Decimal("100"), "ZIG": Decimal("-20")}
        assert (
            decide_import(
                member=core["approver"],
                batch=batch,
                approved=True,
                reason="Retry",
                period=core["period"],
                on_date=date(2026, 1, 1),
            ).pk
            == decision.pk
        )
        assert OpeningEntry.objects.count() == 2
        duplicate = preview_import(
            member=core["maker"],
            kind="opening",
            source=source.replace("100.00", "101.00"),
            source_name="duplicate.csv",
            receivable=core["receivable"],
            offset=opening,
        )
        assert duplicate.errors
        unknown = preview_import(
            member=core["maker"],
            kind="opening",
            source="student_reference,currency,amount,reference\nUNKNOWN,USD,50,UNKNOWN1\n",
            source_name="unknown.csv",
            receivable=core["receivable"],
            offset=opening,
        )
        assert unknown.errors and not unknown.rows


@pytest.mark.django_db
def test_dashboard_uses_real_currency_separated_figures(core):
    from apps.finance.dashboard import dashboard

    with tenant_context(core["tenant"]):
        bill(core)
        payment = pay(core, value="50")
        confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        zig = pay(core, value="20", key="zig-dashboard", currency=core["zig"])
        confirm_payment(member=core["maker"], payment=zig, period=core["period"])
        data = dashboard(core["maker"], start=date(2026, 2, 1), end=date(2026, 2, 28))
        rows = {row["currency"].code: row for row in data["totals"]}
        assert rows["USD"]["billed"] == 150
        assert rows["USD"]["collected"] == 50
        assert rows["USD"]["outstanding"] == 100
        assert rows["USD"]["overdue"] == 100
        assert rows["USD"]["collection_rate"] == Decimal("33.33")
        assert rows["ZIG"]["collected"] == 20
        assert rows["ZIG"]["unallocated"] == 20
        assert rows["ZIG"]["outstanding"] == 0


@pytest.mark.django_db
def test_operational_pages_and_upload_preview(client, core):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(core["maker"].user)
    for url in [
        "/finance/",
        "/finance/cash-up/",
        "/finance/cash-up/new/",
        "/finance/imports/",
        "/finance/imports/new/",
        "/finance/reconciliation/",
        "/finance/reconciliation/new/",
    ]:
        assert client.get(url).status_code == 200, url
    with tenant_context(core["tenant"]):
        bank = configure(
            Account, {"code": "BANK2", "name": "Bank account", "kind": "asset", "purpose": "bank"}, core["approver"]
        )
    file = SimpleUploadedFile(
        "statement.csv", b"date,reference,amount,currency\n2026-02-02,REF001,30.00,USD\n", content_type="text/csv"
    )
    response = client.post(
        "/finance/imports/new/",
        {"kind": "statement", "file": file, "account": str(bank.pk), "currency": str(core["usd"].pk)},
    )
    assert response.status_code == 302
    assert client.get(response.url).status_code == 200
