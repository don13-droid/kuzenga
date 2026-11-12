# ruff: noqa: F811
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction

from apps.core.context import tenant_context
from apps.finance.models import AllocationRetraction, Invoice, Journal, PaymentAllocation
from apps.finance.services import balances
from apps.finance.workflows import (
    active_allocations,
    allocate_payment,
    confirm_payment,
    document_write,
    invoice_outstanding,
    retract_allocation,
)
from tests.test_finance_foundation import finance  # noqa: F401
from tests.test_finance_workflows import bill, core, pay  # noqa: F401


@pytest.mark.django_db
def test_finance_reports_statement_exports_and_pdf_artifacts(core, client):
    import re
    from io import BytesIO
    from pathlib import Path

    from PIL import Image

    from apps.finance.reporting import KINDS, report_data

    with tenant_context(core["tenant"]):
        bill(core)
        payment = pay(core)
        receipt = confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        headers, rows = report_data(core["maker"], "trial")
        assert sum((r[3] for r in rows), Decimal(0)) == sum((r[4] for r in rows), Decimal(0))
        assert {r[0] for r in rows} == {"USD"}
    client.force_login(core["maker"].user)
    for kind, _label in KINDS:
        response = client.get("/finance/reports/", {"kind": kind, "format": "csv"})
        assert response.status_code == 200, kind
        assert response["Content-Type"].startswith("text/csv"), kind
        assert response["Cache-Control"] == "private, no-store"
    invalid = client.get("/finance/reports/", {"kind": "ledger", "currency": "invalid", "format": "csv"})
    assert invalid.status_code == 200 and invalid.context["form"].errors["currency"]
    documents = {
        "receipt": client.get(f"/finance/receipts/{receipt.pk}/print.pdf"),
        "statement": client.get(
            f"/finance/students/{core['student'].pk}/", {"currency": str(core["usd"].pk), "format": "pdf"}
        ),
        "trial": client.get("/finance/reports/", {"kind": "trial", "format": "pdf"}),
    }
    destination = Path("build/finance-acceptance")
    destination.mkdir(parents=True, exist_ok=True)
    for name, response in documents.items():
        assert response.status_code == 200, name
        assert response["Content-Type"] == "application/pdf", name
        assert response.content.startswith(b"%PDF-")
        assert response["Cache-Control"] == "private, no-store"
        (destination / f"{name}.pdf").write_bytes(response.content)
        jpeg = re.search(b"\xff\xd8.*?\xff\xd9", response.content, re.S)
        assert jpeg, name
        Image.open(BytesIO(jpeg.group())).save(destination / f"{name}.png")
        last_jpeg = list(re.finditer(b"\xff\xd8.*?\xff\xd9", response.content, re.S))[-1]
        Image.open(BytesIO(last_jpeg.group())).save(destination / f"{name}-last.png")
    # Stress page breaks using the same renderer as all exported financial documents.
    from apps.finance.receipt_pdf import document_chunks, document_pages, generate_document

    chunks = document_chunks(["Header"] * 5 + ["Record 1"] + ["USD debit 150.00"] * 19 + ["Record 2"] + ["Closing balance USD 100.00"] * 19)
    assert len(chunks) == 2
    assert chunks[1][0] == "Record 2" and chunks[1][-1] == "Closing balance USD 100.00"

    lines = [
        core["tenant"].name,
        "Synthetic long report USD 150.00",
        *[f"ROW {i}: reference TEST-{i} debit USD 150.00 / credit USD 50.00" for i in range(90)],
    ]
    pages = document_pages(core["tenant"], "MULTIPAGE-TEST", lines)
    assert len(pages) == 3
    pages[-1].save(destination / "multipage-last.png")
    pdf = generate_document(core["tenant"], "MULTIPAGE-TEST", lines)
    assert len(re.findall(rb"/Type /Page\b", pdf)) == 3
    (destination / "multipage.pdf").write_bytes(pdf)


@pytest.mark.django_db
def test_plan_amendment_requires_different_approver(core):
    from apps.finance.workflows import arrange_payment, arrangement_status

    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        old = arrange_payment(
            member=core["maker"],
            invoice=invoice,
            schedule=[{"due": "2026-03-01", "amount": "150"}],
            reason="Agreed",
            idempotency_key="original-plan",
        )
        data = dict(
            invoice=invoice,
            schedule=[{"due": "2026-04-01", "amount": "150"}],
            supersedes=old,
            reason="Approved extension",
            idempotency_key="amended-plan",
        )
        with pytest.raises(PermissionDenied):
            arrange_payment(member=core["maker"], **data)
        new = arrange_payment(member=core["approver"], **data)
        assert new.supersedes_id == old.pk
        old.refresh_from_db()
        assert arrangement_status(old) == "superseded"


@pytest.mark.django_db
def test_reconciliation_release_rematch_and_security(core, client):
    from apps.finance.models import Account, ReconciledEntry, StatementRow
    from apps.finance.operations import decide_import, decide_match, preview_import, release_match, request_match
    from apps.finance.services import configure
    from apps.tenancy.models import Membership, Role
    from tests.conftest import make_tenant, make_user

    with tenant_context(core["tenant"]):
        bank = configure(
            Account, {"code": "BANK", "name": "Bank", "kind": "asset", "purpose": "bank"}, core["approver"]
        )
        payment = pay(core, receiving_account=bank, method="bank_transfer", external_reference="MATCH-1")
        confirm_payment(
            member=core["maker"],
            payment=payment,
            period=core["period"],
            verified=True,
            verification_reference="Bank verified",
        )
        batch = preview_import(
            member=core["maker"],
            kind="statement",
            source="date,reference,amount\n2026-02-02,MATCH-1,50\n",
            source_name="statement.csv",
            account=bank,
            currency=core["usd"],
        )
        decide_import(member=core["approver"], batch=batch, approved=True, reason="Source checked")
        row = StatementRow.objects.get(batch=batch)
        line = payment.decision.journal.lines.get(account=bank)
        proposal = request_match(
            member=core["maker"], row=row, line=line, reason="Checked", idempotency_key="first-match"
        )
        decide_match(member=core["approver"], match=proposal, approved=True, reason="Independent check")
        entry = ReconciledEntry.objects.get(row=row)
        with pytest.raises(PermissionDenied):
            release_match(member=core["approver"], entry=entry, reason="Own decision")
        owner_user = make_user(core["tenant"], Role.OWNER)
        owner = Membership.objects.get(user=owner_user, tenant=core["tenant"])
        release_match(member=owner, entry=entry, reason="Matching evidence corrected")
        with pytest.raises(ValidationError):
            release_match(member=owner, entry=entry, reason="Again")
        replacement = request_match(
            member=core["maker"],
            row=row,
            line=line,
            reason="Rechecked corrected evidence",
            idempotency_key="second-match",
        )
        decide_match(member=core["approver"], match=replacement, approved=True, reason="Independent recheck")
        assert ReconciledEntry.objects.filter(row=row).count() == 2
        assert ReconciledEntry.objects.filter(row=row, release__isnull=True).count() == 1
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM finance_reconciledentry WHERE id=%s",
                [entry.pk.hex if connection.vendor == "sqlite" else entry.pk],
            )
    client.force_login(owner_user)
    assert client.get("/finance/reconciliation/").status_code == 200
    other = make_tenant("finance-acceptance-other", "professional")
    other_user = make_user(other, Role.ADMIN)
    client.force_login(other_user)
    assert client.get(f"/finance/reconciliation/{entry.pk}/release/").status_code == 404
    assert (
        client.get(
            f"/finance/students/{core['student'].pk}/", {"currency": str(core["usd"].pk), "format": "pdf"}
        ).status_code
        == 404
    )
    client.force_login(core["maker"].user)
    assert client.get(f"/finance/reconciliation/{entry.pk}/release/").status_code == 403


@pytest.mark.django_db
def test_retraction_cross_tenant_reports_permissions_and_csv_safety(core, client, monkeypatch):
    from apps.finance import reporting
    from apps.finance.report_views import csv_cell
    from apps.tenancy.models import Role
    from tests.conftest import make_tenant, make_user

    with tenant_context(core["tenant"]):
        bill(core)
        payment = pay(core)
        receipt = confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        allocation = PaymentAllocation.objects.get(decision__payment=payment)
    other = make_tenant("finance-denied", "professional")
    client.force_login(make_user(other, Role.ADMIN))
    assert client.get(f"/finance/allocations/{allocation.pk}/retract/").status_code == 404
    assert client.get(f"/finance/receipts/{receipt.pk}/print.pdf").status_code == 404
    client.force_login(make_user(core["tenant"], Role.TEACHER))
    assert client.get("/finance/reports/").status_code == 403
    client.force_login(core["maker"].user)
    assert client.get(f"/finance/allocations/{allocation.pk}/retract/").status_code == 403
    monkeypatch.setattr(reporting, "LIMIT", 1)
    response = client.get("/finance/reports/", {"kind": "ledger", "format": "csv"})
    assert response.context["form"].non_field_errors()
    assert response["Content-Type"].startswith("text/html")
    assert csv_cell(" =HYPERLINK('bad')").startswith("'")
    assert csv_cell(Decimal("-20.00")) == "-20.00"


@pytest.mark.django_db
def test_allocation_retraction_preserves_money_history_and_allows_other_invoice(core, client):
    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        payment = pay(core)
        receipt = confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        allocation = PaymentAllocation.objects.get(decision__payment=payment)
        original_snapshot = receipt.snapshot.copy()
        journals = Journal.objects.count()
        with pytest.raises(PermissionDenied):
            retract_allocation(
                member=core["maker"], allocation=allocation, on_date=date(2026, 2, 3), reason="Wrong invoice"
            )
        with pytest.raises(ValidationError):
            retract_allocation(member=core["approver"], allocation=allocation, on_date=date(2026, 2, 3), reason=" ")
        retract_allocation(
            member=core["approver"], allocation=allocation, on_date=date(2026, 2, 3), reason="Wrong invoice"
        )
        assert invoice_outstanding(invoice) == 150
        assert active_allocations(date(2026, 2, 2)).filter(pk=allocation.pk).exists()
        assert not active_allocations(date(2026, 2, 3)).filter(pk=allocation.pk).exists()
        assert balances(core["maker"], core["student"])["USD"] == Decimal(100)
        assert Journal.objects.count() == journals
        receipt.refresh_from_db()
        assert receipt.snapshot == original_snapshot
        assert PaymentAllocation.objects.filter(pk=allocation.pk).exists()
        with pytest.raises(ValidationError):
            retract_allocation(member=core["approver"], allocation=allocation, on_date=date(2026, 2, 3), reason="Retry")
        with pytest.raises(ValidationError):
            allocate_payment(member=core["maker"], payment=payment, invoice=invoice, value="50")
        with pytest.raises(ValidationError):
            AllocationRetraction.objects.all().delete()
        # A released payment can settle a different charge, retaining its first allocation.
        from apps.finance.models import FeeRule
        from apps.finance.services import configure

        fee_data = {
            f.name: getattr(core["fee"], f.name)
            for f in core["fee"]._meta.fields
            if f.name not in ("id", "created_at", "updated_at", "tenant")
        }
        fee_data.update(code="EXTRA", name="Additional charge", amount=Decimal(50))
        fee = configure(FeeRule, fee_data, core["maker"])
        from apps.finance.workflows import bill_students

        second = bill_students(
            member=core["maker"],
            fee=fee,
            on_date=date(2026, 2, 3),
            period=core["period"],
            receivable_account=core["receivable"],
        )[0]
        replacement = allocate_payment(member=core["maker"], payment=payment, invoice=second, value="50", on_date=date(2026, 2, 4))
        assert not active_allocations(date(2026, 2, 3)).filter(pk=replacement.pk).exists()
        assert active_allocations(date(2026, 2, 4)).filter(pk=replacement.pk).exists()
        assert invoice_outstanding(second) == 0
        assert Invoice.objects.count() == 2
    client.force_login(core["approver"].user)
    assert client.get(f"/finance/payments/{payment.pk}/").status_code == 200


@pytest.mark.django_db
def test_allocation_retraction_rollback_and_raw_guards(core):
    with tenant_context(core["tenant"]):
        invoice = bill(core)[0]
        payment = pay(core)
        confirm_payment(member=core["maker"], payment=payment, period=core["period"])
        allocation = PaymentAllocation.objects.get(decision__payment=payment)
        with pytest.raises(RuntimeError), transaction.atomic():
            retract_allocation(
                member=core["approver"], allocation=allocation, on_date=date(2026, 2, 3), reason="Rollback"
            )
            raise RuntimeError("Abort whole operation")
        assert invoice_outstanding(invoice) == 100
        assert not AllocationRetraction.objects.exists()
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE finance_paymentallocation SET amount=1 WHERE id=%s",
                [allocation.pk.hex if connection.vendor == "sqlite" else allocation.pk],
            )
        with pytest.raises(DatabaseError), transaction.atomic(), document_write():
            AllocationRetraction.objects.create(
                allocation=allocation, actor=core["approver"], date=date(2026, 1, 1), reason="Before payment"
            )
