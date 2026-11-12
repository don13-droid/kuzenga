"""Core fee billing, payment, receipt and collection workflows over the existing ledger."""

import hashlib
import json
from contextlib import contextmanager
from datetime import date as date_type
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import audit
from apps.students.models import Student, StudentEnrolment
from apps.tenancy.models import Tenant

from .models import (
    Account,
    AccountingPeriod,
    Currency,
    DebtFollowUp,
    DocumentSequence,
    FeeRule,
    Invoice,
    Journal,
    JournalLine,
    Payment,
    PaymentAllocation,
    PaymentArrangement,
    PaymentDecision,
    Receipt,
    StudentAccount,
    _ledger_write,
)
from .services import _scope, amount, authorize, balances, post_journal, reverse_journal, student_account

ZERO = Decimal("0")


@contextmanager
def document_write():
    marker = _ledger_write.set(True)
    try:
        yield
    finally:
        _ledger_write.reset(marker)


def number(kind):
    """Caller holds the tenant row lock and atomic transaction."""
    sequence, _ = DocumentSequence.objects.get_or_create(kind=kind)
    sequence.last_number += 1
    sequence.save()
    return f"{kind}-{sequence.last_number:08d}"


def lock(member, permission):
    member = authorize(member, permission)
    Tenant.objects.select_for_update().get(pk=member.tenant_id)
    return member


def eligible_students(fee, on_date):
    if not fee.effective_from <= on_date <= fee.effective_to:
        raise ValidationError("Billing date must fall within this fee version's effective dates.")
    qs = StudentEnrolment.objects.filter(
        class_group__academic_year=fee.academic_year, effective_from__lte=on_date
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
    if fee.class_group_id:
        qs = qs.filter(class_group=fee.class_group)
    if fee.grade_id:
        qs = qs.filter(class_group__grade=fee.grade)
    if fee.term_id and not fee.term.start_date <= on_date <= fee.term.end_date:
        raise ValidationError("Billing date must fall within the fee's academic term.")
    return Student.objects.filter(pk__in=qs.values("student_id")).order_by("last_name", "first_name", "pk")


def billing_preview(
    member, fee, on_date, students=None, class_group=None, boarding_status="", student_category="", opt_in=False
):
    authorize(member, "finance.post")
    fee = _scope(FeeRule, fee)
    if fee.boarding_status and fee.boarding_status != boarding_status:
        raise ValidationError("Explicitly select the matching boarding/day cohort.")
    if fee.student_category and fee.student_category != student_category:
        raise ValidationError("Explicitly select the matching student category.")
    if fee.optional and not opt_in:
        raise ValidationError("Optional services require explicit opt-in for the selected students.")
    qs = eligible_students(fee, on_date)
    if class_group:
        from apps.academics.models import ClassGroup

        classroom = _scope(ClassGroup, class_group)
        placements = StudentEnrolment.objects.filter(class_group=classroom, effective_from__lte=on_date).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=on_date)
        )
        qs = qs.filter(pk__in=placements.values("student_id"))
    if students is not None:
        keys = [str(getattr(student, "pk", student)) for student in students]
        if len(keys) != len(set(keys)):
            raise ValidationError("Duplicate student in billing request.")
        selected = list(qs.filter(pk__in=keys))
        if len(selected) != len(keys):
            raise ValidationError("A selected student is outside this school's fee/enrolment scope.")
    else:
        selected = list(qs[:201])
    if not selected or len(selected) > 200:
        raise ValidationError("Select 1–200 eligible students; split larger billing runs by class.")
    existing = set(
        Invoice.objects.filter(fee=fee, student_account__student__in=selected).values_list(
            "student_account__student_id", flat=True
        )
    )
    return {
        "students": selected,
        "existing": existing,
        "total": fee.amount * (len(selected) - len(existing)),
        "fee": fee,
    }


@transaction.atomic
def bill_students(*, member, fee, on_date, period, receivable_account, students=None, **eligibility):
    member = lock(member, "finance.post")
    fee = _scope(FeeRule, fee)
    period = _scope(AccountingPeriod, period)
    receivable = _scope(Account, receivable_account)
    if receivable.purpose != "receivable" or receivable.kind != "asset":
        raise ValidationError("Select a student receivable asset account.")
    preview = billing_preview(member, fee, on_date, students=students, **eligibility)
    result = []
    for student in preview["students"]:
        account = student_account(student, member)
        existing = Invoice.objects.filter(student_account=account, fee=fee).select_related("journal").first()
        if existing:
            if existing.issue_date != on_date or existing.journal.period_id != period.pk:
                raise ValidationError("This fee has already been billed using a different posting date or period.")
            result.append(existing)
            continue
        ref = number("INV")
        journal = post_journal(
            member=member,
            reference=ref,
            idempotency_key=f"billing:{fee.pk}:{student.pk}",
            date=on_date,
            period=period,
            currency=fee.currency,
            description=f"Fee {fee.code}: {fee.name}",
            source="student_invoice",
            source_reference=ref,
            lines=[
                {"account": receivable, "student_account": account, "debit": fee.amount},
                {"account": fee.income_account, "credit": fee.amount},
            ],
        )
        with document_write():
            invoice = Invoice.objects.create(
                number=ref,
                student_account=account,
                fee=fee,
                journal=journal,
                currency=fee.currency,
                amount=fee.amount,
                issue_date=on_date,
                due_date=fee.due_date,
                snapshot={
                    "student": student.full_name,
                    "admission": student.admission_number,
                    "fee": fee.name,
                    "code": fee.code,
                    "currency": fee.currency.code,
                    "boarding_status": eligibility.get("boarding_status", ""),
                    "student_category": eligibility.get("student_category", ""),
                    "optional_opt_in": eligibility.get("opt_in", False),
                },
            )
        audit.record("finance.invoice_posted", actor=member.user, obj=invoice, reference=ref, amount=fee.amount)
        result.append(invoice)
    return result


def active_allocations(on_date=None):
    qs = PaymentAllocation.objects.filter(decision__journal__posted=True)
    if on_date:
        return qs.filter(Q(effective_date__isnull=True) | Q(effective_date__lte=on_date)).filter(Q(retraction__isnull=True) | Q(retraction__date__gt=on_date)).filter(decision__journal__date__lte=on_date).filter(
            Q(decision__journal__reversal__isnull=True) | Q(decision__journal__reversal__date__gt=on_date)
        )
    return qs.filter(decision__journal__reversal__isnull=True, retraction__isnull=True)


@transaction.atomic
def retract_allocation(*, member, allocation, on_date, reason):
    """Release invoice settlement, not cash or student credit; retain original allocation."""
    from .models import AllocationRetraction

    member = lock(member, "finance.approve")
    allocation = _scope(PaymentAllocation, allocation)
    if not reason.strip() or len(reason) > 1000:
        raise ValidationError("A correction reason of at most 1000 characters is required.")
    if AllocationRetraction.objects.filter(allocation=allocation).exists():
        raise ValidationError("This allocation has already been retracted.")
    if not active_allocations().filter(pk=allocation.pk).exists():
        raise ValidationError("Only an active allocation can be retracted.")
    if on_date < (allocation.effective_date or allocation.decision.journal.date) or on_date > timezone.localdate():
        raise ValidationError("Retraction date must be between the payment posting date and today.")
    # Do not change a closed accounting period's settlement history.
    if not AccountingPeriod.objects.filter(starts_on__lte=on_date, ends_on__gte=on_date, closed=False).exists():
        raise ValidationError("Retraction requires an open accounting period covering its date.")
    with document_write():
        result = AllocationRetraction.objects.create(allocation=allocation, actor=member, date=on_date, reason=reason)
    audit.record("finance.allocation_retracted", actor=member.user, obj=result,
                 allocation=str(allocation.pk), invoice=allocation.invoice.number,
                 payment=allocation.decision.payment.number, reason=reason)
    return result


def invoice_paid(invoice):
    return sum(active_allocations().filter(invoice=invoice).values_list("amount", flat=True), ZERO)


def invoice_balance_map(invoices, on_date=None):
    """Batch Decimal aggregation avoids N+1 queries and SQLite floating-point SUM."""
    invoices = list(invoices)
    result = {i.pk: {"paid": ZERO, "outstanding": i.amount} for i in invoices}
    for invoice_id, value in (
        active_allocations(on_date)
        .filter(invoice_id__in=result)
        .values_list("invoice_id", "amount")
        .iterator(chunk_size=500)
    ):
        result[invoice_id]["paid"] += value
    from .models import InvoiceAdjustment

    adjustments = InvoiceAdjustment.objects.filter(invoice_id__in=result)
    if on_date:
        adjustments = adjustments.filter(journal__date__lte=on_date).filter(
            Q(journal__reversal__isnull=True) | Q(journal__reversal__date__gt=on_date)
        )
    else:
        adjustments = adjustments.filter(journal__reversal__isnull=True)
    for invoice_id, direction, value in adjustments.values_list("invoice_id", "direction", "amount").iterator(
        chunk_size=500
    ):
        result[invoice_id]["outstanding"] += value if direction == "debit" else -value
    reversals = Journal.objects.filter(reversal_of_id__in=[i.journal_id for i in invoices])
    if on_date:
        reversals = reversals.filter(date__lte=on_date)
    reversed_journals = set(reversals.values_list("reversal_of_id", flat=True))
    for invoice in invoices:
        result[invoice.pk]["outstanding"] = (
            ZERO
            if invoice.journal_id in reversed_journals
            else result[invoice.pk]["outstanding"] - result[invoice.pk]["paid"]
        )
    return result


def invoice_outstanding(invoice):
    return invoice_balance_map([invoice])[invoice.pk]["outstanding"]


def payment_state(payment, *, known_decision=None):
    # Service callers may hold stale model instances after confirmation or reversal.
    decision = (
        known_decision
        if known_decision is not None
        else PaymentDecision.objects.filter(payment=payment).select_related("journal__reversal").first()
    )
    if not decision:
        return "pending"
    if not decision.journal_id:
        return "rejected"
    return "reversed" if getattr(decision.journal, "reversal", None) else "confirmed"


@transaction.atomic
def record_payment(
    *,
    member,
    student,
    currency,
    value,
    method,
    receiving_account,
    receivable_account,
    on_date,
    idempotency_key,
    external_reference="",
    evidence_reference="",
):
    member = lock(member, "finance.post")
    account, currency = _scope(StudentAccount, student), _scope(Currency, currency)
    receiving, receivable = _scope(Account, receiving_account), _scope(Account, receivable_account)
    value = amount(value, currency)
    external_reference = external_reference.strip().upper()
    if value <= 0 or not currency.is_active or method not in dict(Payment.METHODS) or not idempotency_key.strip():
        raise ValidationError("A positive amount, active currency, valid method and request key are required.")
    if method != "cash" and not external_reference:
        raise ValidationError("Electronic payments require an external transaction reference.")
    expected = (
        "cash"
        if method == "cash"
        else "bank"
        if method in ("bank_transfer", "bank_deposit", "pos")
        else "mobile_clearing"
        if method in ("ecocash", "onemoney", "innbucks")
        else None
    )
    if receiving.kind != "asset" or (expected and receiving.purpose != expected) or not receiving.is_active:
        raise ValidationError("Receiving account does not match the selected payment method.")
    if receivable.purpose != "receivable" or not receivable.is_active:
        raise ValidationError("Choose an active student receivable account.")
    payload = {
        "student": str(account.pk),
        "currency": str(currency.pk),
        "amount": str(value),
        "method": method,
        "receiving": str(receiving.pk),
        "receivable": str(receivable.pk),
        "date": str(on_date),
        "external": external_reference,
        "evidence": evidence_reference,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise ValidationError("Payment request key conflicts with another submission.")
        return existing
    if external_reference and Payment.objects.filter(method=method, external_reference=external_reference).exists():
        raise ValidationError("This provider reference has already been recorded, including any reversed payment.")
    with document_write():
        payment = Payment.objects.create(
            number=number("PAY"),
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            student_account=account,
            currency=currency,
            amount=value,
            method=method,
            receiving_account=receiving,
            receivable_account=receivable,
            date=on_date,
            recorded_by=member,
            external_reference=external_reference,
            evidence_reference=evidence_reference,
        )
    audit.record("finance.payment_recorded", actor=member.user, obj=payment, reference=payment.number, status="pending")
    return payment


@transaction.atomic
def allocate_payment(*, member, payment, invoice, value, on_date=None):
    member = lock(member, "finance.post")
    payment, invoice = _scope(Payment, payment), _scope(Invoice, invoice)
    if payment_state(payment) != "confirmed":
        raise ValidationError("Only confirmed, unreversed payments can be allocated.")
    decision = PaymentDecision.objects.get(payment=payment)
    if payment.student_account_id != invoice.student_account_id or payment.currency_id != invoice.currency_id:
        raise ValidationError("Allocation requires the same student and currency.")
    value = amount(value, payment.currency)
    existing = PaymentAllocation.objects.filter(decision=decision, invoice=invoice).first()
    if existing:
        if hasattr(existing, "retraction"):
            raise ValidationError("This invoice allocation was retracted; use a different invoice or a corrected payment.")
        if existing.amount != value or (on_date and on_date != (existing.effective_date or decision.journal.date)):
            raise ValidationError(
                "An allocation already exists; use an approved correction rather than overwriting it."
            )
        return existing
    from .models import AllocationRetraction
    on_date = on_date or timezone.localdate()
    released = AllocationRetraction.objects.filter(allocation__decision=decision).order_by("-date").first()
    earliest = max(decision.journal.date, invoice.issue_date, released.date if released else decision.journal.date)
    if on_date < earliest or on_date > timezone.localdate():
        raise ValidationError("Allocation date must follow the payment, invoice and any released settlement, and cannot be in the future.")
    used = sum(active_allocations().filter(decision=decision).values_list("amount", flat=True), ZERO)
    from .controls import payment_refund_reservations

    if (
        value <= 0
        or value > payment.amount - used - payment_refund_reservations(payment)
        or value > invoice_outstanding(invoice)
    ):
        raise ValidationError("Allocation exceeds available payment credit or invoice balance.")
    # Control account must agree with the invoice's receivable posting.
    if not invoice.journal.lines.filter(
        account=payment.receivable_account, student_account=payment.student_account
    ).exists():
        raise ValidationError("Payment and invoice use different student receivable control accounts.")
    with document_write():
        allocation = PaymentAllocation.objects.create(decision=decision, invoice=invoice, amount=value, effective_date=on_date)
    audit.record(
        "finance.payment_allocated",
        actor=member.user,
        obj=allocation,
        reference=payment.number,
        invoice=invoice.number,
        amount=value,
    )
    return allocation


@transaction.atomic
def confirm_payment(*, member, payment, period, verification_reference="", verified=False, auto_allocate=True):
    member = lock(member, "finance.post")
    payment = _scope(Payment, payment)
    existing = PaymentDecision.objects.filter(payment=payment).first()
    if existing:
        if payment_state(payment) != "confirmed":
            raise ValidationError("Rejected or reversed payments cannot be confirmed again.")
        return existing.receipt
    if payment.method != "cash" and (not verified or not verification_reference.strip()):
        raise ValidationError("Verify the electronic payment independently and supply its verification reference.")
    if payment.method == "cash":
        from .operations import ensure_cash_open

        ensure_cash_open(payment.recorded_by, payment.date, payment.currency, payment.receiving_account)
    journal = post_journal(
        member=member,
        reference=payment.number,
        idempotency_key=f"payment:{payment.pk}",
        date=payment.date,
        period=period,
        currency=payment.currency,
        description=f"Payment {payment.number}",
        source="student_payment",
        source_reference=payment.number,
        lines=[
            {"account": payment.receiving_account, "debit": payment.amount},
            {
                "account": payment.receivable_account,
                "student_account": payment.student_account,
                "credit": payment.amount,
            },
        ],
    )
    with document_write():
        decision = PaymentDecision.objects.create(
            payment=payment,
            journal=journal,
            actor=member,
            reason="Payment confirmed",
            verification_reference=verification_reference,
        )
    if auto_allocate:
        remaining = payment.amount
        for invoice in Invoice.objects.filter(
            student_account=payment.student_account, currency=payment.currency
        ).order_by("due_date", "issue_date", "number"):
            outstanding = invoice_outstanding(invoice)
            if (
                remaining
                and outstanding > 0
                and invoice.journal.lines.filter(
                    account=payment.receivable_account, student_account=payment.student_account
                ).exists()
            ):
                applied = min(remaining, outstanding)
                allocate_payment(member=member, payment=payment, invoice=invoice, value=applied, on_date=max(payment.date, invoice.issue_date))
                remaining -= applied
    snapshot = {
        "student": payment.student_account.student.full_name,
        "admission": payment.student_account.student.admission_number,
        "account": str(payment.student_account_id),
        "amount": str(payment.amount),
        "currency": payment.currency.code,
        "method": payment.get_method_display(),
        "payment": payment.number,
        "external": payment.external_reference,
        "date": str(payment.date),
        "cashier": str(payment.recorded_by.user),
        "confirmed_by": str(member.user),
        "allocations": [
            {"invoice": a.invoice.number, "amount": str(a.amount)}
            for a in decision.allocations.select_related("invoice")
        ],
        "balance": str(balances(member, payment.student_account).get(payment.currency.code, ZERO)),
    }
    with document_write():
        receipt = Receipt.objects.create(number=number("RCPT"), decision=decision, snapshot=snapshot)
    audit.record("finance.payment_confirmed", actor=member.user, obj=payment, reference=payment.number)
    audit.record("finance.receipt_issued", actor=member.user, obj=receipt, reference=receipt.number)
    return receipt


@transaction.atomic
def reject_payment(*, member, payment, reason):
    member = lock(member, "finance.post")
    payment = _scope(Payment, payment)
    if not reason.strip() or PaymentDecision.objects.filter(payment=payment).exists():
        raise ValidationError("Only pending payments can be rejected, with a reason.")
    with document_write():
        decision = PaymentDecision.objects.create(payment=payment, actor=member, reason=reason)
    audit.record("finance.payment_rejected", actor=member.user, obj=payment, reason=reason)
    return decision


@transaction.atomic
def reverse_payment(*, member, payment, period, on_date, reason):
    member = lock(member, "finance.approve")
    payment = _scope(Payment, payment)
    if payment_state(payment) == "reversed":
        return PaymentDecision.objects.get(payment=payment).journal.reversal
    if payment_state(payment) != "confirmed":
        raise ValidationError("Only confirmed payments can be reversed.")
    if payment.method == "cash":
        from .operations import ensure_cash_open

        ensure_cash_open(payment.recorded_by, on_date, payment.currency, payment.receiving_account)
    decision = PaymentDecision.objects.get(payment=payment)
    from django.core.exceptions import PermissionDenied

    if member.user_id in (payment.recorded_by.user_id, decision.actor.user_id):
        raise PermissionDenied("A different authorised person must approve the payment reversal.")
    reversal = reverse_journal(
        decision.journal,
        member=member,
        reference=number("REV"),
        idempotency_key=f"payment-reversal:{payment.pk}",
        date=on_date,
        period=period,
        reason=reason,
    )
    audit.record(
        "finance.payment_reversed",
        actor=member.user,
        obj=payment,
        reference=payment.number,
        receipt=decision.receipt.number,
        reason=reason,
    )
    return reversal


@transaction.atomic
def arrange_payment(*, member, invoice, schedule, reason, idempotency_key, supersedes=None):
    member = lock(member, "finance.fees")
    invoice = _scope(Invoice, invoice)
    prior = _scope(PaymentArrangement, supersedes) if supersedes else None
    if prior:
        authorize(member, "finance.approve")
        if prior.actor.user_id == member.user_id:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("A different approver must amend this payment plan.")
    normalized = []
    for item in schedule:
        try:
            due = item["due"] if type(item["due"]) is date_type else date_type.fromisoformat(item["due"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Each instalment requires a valid due date.") from exc
        value = amount(item["amount"], invoice.currency)
        if value <= 0:
            raise ValidationError("Instalments must be positive.")
        normalized.append({"due": due.isoformat(), "amount": str(value)})
    normalized.sort(key=lambda item: item["due"])
    existing = PaymentArrangement.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.invoice_id != invoice.pk or existing.schedule != normalized or existing.reason != reason or existing.supersedes_id != (prior.pk if prior else None):
            raise ValidationError("Arrangement request key conflicts with a previous submission.")
        return existing
    if (
        not normalized
        or len(normalized) > 24
        or not reason.strip()
        or sum(Decimal(i["amount"]) for i in normalized) != invoice_outstanding(invoice)
    ):
        raise ValidationError("Provide a reason and 1–24 instalments totalling the current invoice balance.")
    current = PaymentArrangement.objects.filter(invoice=invoice, replacement__isnull=True).first()
    if (current and not prior) or (prior and (not current or prior.invoice_id != invoice.pk or current.pk != prior.pk)):
        raise ValidationError("Explicitly supersede the current arrangement when amending its schedule.")
    with document_write():
        result = PaymentArrangement.objects.create(
            invoice=invoice,
            schedule=normalized,
            baseline_paid=invoice_paid(invoice),
            reason=reason,
            actor=member,
            idempotency_key=idempotency_key,
            supersedes=prior,
        )
    audit.record("finance.payment_arranged", actor=member.user, obj=result, invoice=invoice.number, reason=reason)
    return result


@transaction.atomic
def follow_up(*, member, invoice, note, idempotency_key, promised_date=None):
    member = lock(member, "finance.fees")
    invoice = _scope(Invoice, invoice)
    existing = DebtFollowUp.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if (existing.invoice_id, existing.note, existing.promised_date) != (invoice.pk, note, promised_date):
            raise ValidationError("Follow-up key conflicts with another submission.")
        return existing
    if not note.strip():
        raise ValidationError("A collection note is required.")
    with document_write():
        result = DebtFollowUp.objects.create(
            invoice=invoice, actor=member, note=note, idempotency_key=idempotency_key, promised_date=promised_date
        )
    audit.record("finance.debt_follow_up", actor=member.user, obj=result, invoice=invoice.number)
    return result


def arrangement_status(arrangement, on_date=None):
    if getattr(arrangement, "replacement", None) is not None:
        return "superseded"
    on_date = on_date or timezone.localdate()
    paid = max(ZERO, invoice_paid(arrangement.invoice) - arrangement.baseline_paid)
    expected = sum(
        (Decimal(i["amount"]) for i in arrangement.schedule if date_type.fromisoformat(i["due"]) < on_date), ZERO
    )
    return (
        "settled"
        if invoice_outstanding(arrangement.invoice) <= 0
        else "missed instalment"
        if paid < expected
        else "on schedule"
    )


def debt_rows(member, currency=None, on_date=None, bands=(30, 60, 90), minimum=ZERO):
    authorize(member, "finance.view")
    on_date = on_date or timezone.localdate()
    if (
        not bands
        or list(bands) != sorted(set(bands))
        or any(not isinstance(x, int) or x < 1 or x > 3650 for x in bands)
    ):
        raise ValidationError("Ageing bands must be ascending distinct positive day counts, up to 3650.")
    qs = Invoice.objects.select_related("student_account__student", "currency", "fee__grade", "fee__class_group")
    if currency:
        qs = qs.filter(currency=_scope(Currency, currency))
    rows = []
    invoices = list(qs.filter(issue_date__lte=on_date))
    amounts = invoice_balance_map(invoices, on_date)
    for invoice in invoices:
        outstanding = amounts[invoice.pk]["outstanding"]
        if outstanding <= 0 or outstanding < minimum:
            continue
        days = (on_date - invoice.due_date).days
        bucket = "Current" if days <= 0 else f"Over {bands[-1]} days"
        lower = 1
        for upper in bands:
            if 0 < days <= upper:
                bucket = f"{lower}–{upper} days"
                break
            lower = upper + 1
        rows.append({"invoice": invoice, "outstanding": outstanding, "days": max(0, days), "bucket": bucket})
    return rows


def student_debt_balances(member, currency=None, on_date=None):
    """Include opening/manual receivables even when no invoice exists."""
    authorize(member, "finance.view")
    on_date = on_date or timezone.localdate()
    qs = JournalLine.objects.filter(
        journal__posted=True, journal__date__lte=on_date, student_account__isnull=False
    ).select_related("student_account__student", "journal__currency")
    if currency:
        qs = qs.filter(journal__currency=_scope(Currency, currency))
    groups = {}
    for line in qs.iterator(chunk_size=500):
        key = (line.student_account_id, line.journal.currency_id)
        row = groups.setdefault(
            key, {"account": line.student_account, "currency": line.journal.currency, "balance": ZERO}
        )
        row["balance"] += line.debit - line.credit
    return sorted(
        groups.values(),
        key=lambda r: (r["account"].student.last_name, r["account"].student.first_name, r["currency"].code),
    )
