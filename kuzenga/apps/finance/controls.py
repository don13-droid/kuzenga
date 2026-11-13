"""Append-only approvals for concessions, notes, write-offs and refund recording."""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.core import audit

from .models import (
    Account,
    FinanceDecision,
    FinanceRequest,
    Invoice,
    InvoiceAdjustment,
    Journal,
    JournalLine,
    Payment,
    RefundClosure,
    RefundDisbursement,
)
from .services import _scope, amount, post_journal, reverse_journal
from .workflows import document_write, invoice_outstanding, lock, number

CONCESSIONS = {"discount", "scholarship", "bursary", "sibling", "staff_child", "waiver"}


def credit_available(account, currency, receivable):
    balance = sum(
        (
            d - c
            for d, c in JournalLine.objects.filter(
                student_account=account, account=receivable, journal__posted=True, journal__currency=currency
            ).values_list("debit", "credit")
        ),
        Decimal(0),
    )
    return max(Decimal(0), -balance)


def reserved_refunds(account, currency, receivable, exclude=None):
    qs = FinanceDecision.objects.filter(
        approved=True,
        request__kind="refund",
        request__student_account=account,
        request__currency=currency,
        request__receivable_account=receivable,
        disbursement__isnull=True,
        closure__isnull=True,
        request__payment__decision__journal__reversal__isnull=True,
    )
    if exclude:
        qs = qs.exclude(pk=exclude)
    return sum(qs.values_list("amount", flat=True), Decimal(0))


def payment_refund_reservations(payment, exclude=None):
    from django.db.models import Q

    qs = FinanceDecision.objects.filter(
        approved=True, request__kind="refund", request__payment=payment, closure__isnull=True
    )
    if exclude:
        qs = qs.exclude(pk=exclude)
    return sum(
        qs.filter(Q(disbursement__isnull=True) | Q(disbursement__journal__reversal__isnull=True)).values_list(
            "amount", flat=True
        ),
        Decimal(0),
    )


@transaction.atomic
def request_control(
    *,
    member,
    kind,
    invoice=None,
    payment=None,
    student_account=None,
    currency=None,
    receivable_account=None,
    counter_account,
    mode,
    value,
    benefit_code,
    effective_from,
    effective_to,
    eligibility,
    reason,
    supporting_reference,
    idempotency_key,
):
    member = lock(member, "finance.fees")
    if kind not in dict(FinanceRequest.KINDS) or mode not in ("fixed", "percentage"):
        raise ValidationError("Select a supported financial request type and calculation mode.")
    invoice = _scope(Invoice, invoice) if invoice else None
    if invoice:
        student_account, currency = invoice.student_account, invoice.currency
        line = invoice.journal.lines.filter(student_account=student_account, debit__gt=0).first()
        receivable = line.account
    else:
        if kind != "refund":
            raise ValidationError("An existing invoice is required for concessions, notes and write-offs.")
        from .workflows import payment_state

        payment = _scope(Payment, payment)
        for supplied, expected in [
            (student_account, payment.student_account_id),
            (currency, payment.currency_id),
            (receivable_account, payment.receivable_account_id),
        ]:
            if supplied is not None and str(getattr(supplied, "pk", supplied)) != str(expected):
                raise ValidationError(
                    "Refund student, currency or control account does not match its original payment."
                )
        if payment_state(payment) != "confirmed":
            raise ValidationError("Refunds require an original confirmed, unreversed payment.")
        student_account, currency = payment.student_account, payment.currency
        receivable = payment.receivable_account
    counter = _scope(Account, counter_account)
    benefit_code = benefit_code.strip().upper()
    if not benefit_code or not reason.strip() or not eligibility.strip() or not supporting_reference.strip():
        raise ValidationError(
            "A benefit/reference code, reason, eligibility attestation and supporting reference are required."
        )
    if effective_from > effective_to or (invoice and not effective_from <= invoice.issue_date <= effective_to):
        raise ValidationError("Effective dates must be ordered and cover the invoice issue date.")
    if receivable.purpose != "receivable" or not receivable.is_active or not counter.is_active:
        raise ValidationError("Select active, appropriate receivable and counter accounts.")
    if kind in CONCESSIONS and (counter.purpose != "concession" or counter.kind not in ("income", "expense")):
        raise ValidationError("Concessions require an expense or contra-income account with concession purpose.")
    if kind == "write_off" and (counter.kind != "expense" or counter.purpose != "bad_debt"):
        raise ValidationError("Write-offs require a bad-debt expense account.")
    if kind in ("credit", "debit") and counter.kind not in ("income", "expense"):
        raise ValidationError("Notes require an income or expense counter account.")
    if kind == "refund" and (
        invoice
        or mode != "fixed"
        or counter.kind != "asset"
        or counter.purpose not in ("cash", "bank", "mobile_clearing")
    ):
        raise ValidationError("Refunds require an account credit and an approved cash/bank/mobile asset account.")
    if mode == "percentage":
        if isinstance(value, (float, bool)):
            raise ValidationError("Use an exact Decimal percentage.")
        try:
            value = Decimal(value)
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise ValidationError("Invalid percentage.") from exc
        if not invoice or not value.is_finite() or value <= 0 or value > 100:
            raise ValidationError("Percentage must be greater than zero and at most 100.")
    else:
        value = amount(value, currency)
        if value <= 0:
            raise ValidationError("A positive amount is required.")
    payload = {
        "kind": kind,
        "invoice": str(invoice.pk) if invoice else None,
        "payment": str(payment.pk) if payment else None,
        "student": str(student_account.pk),
        "currency": str(currency.pk),
        "receivable": str(receivable.pk),
        "counter": str(counter.pk),
        "mode": mode,
        "value": str(value),
        "code": benefit_code,
        "from": str(effective_from),
        "to": str(effective_to),
        "eligibility": eligibility,
        "reason": reason,
        "support": supporting_reference,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = FinanceRequest.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise ValidationError("Financial request key conflicts with another submission.")
        return existing
    if invoice and FinanceRequest.objects.filter(invoice=invoice, benefit_code=benefit_code).exists():
        raise ValidationError("This benefit/reference has already been requested for this invoice.")
    with document_write():
        result = FinanceRequest.objects.create(
            number=number("REQ"),
            kind=kind,
            invoice=invoice,
            payment=payment,
            student_account=student_account,
            currency=currency,
            receivable_account=receivable,
            counter_account=counter,
            mode=mode,
            value=value,
            benefit_code=benefit_code,
            effective_from=effective_from,
            effective_to=effective_to,
            eligibility=eligibility,
            reason=reason,
            supporting_reference=supporting_reference,
            requester=member,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        )
    audit.record("finance.control_requested", actor=member.user, obj=result, reference=result.number, kind=kind)
    return result


@transaction.atomic
def decide_control(*, member, request, approved, reason, on_date, period):
    member = lock(member, "finance.approve")
    request = _scope(FinanceRequest, request)
    if member.user_id == request.requester.user_id:
        raise PermissionDenied("A different authorised person must decide this request.")
    existing = FinanceDecision.objects.filter(request=request).first()
    if existing:
        if existing.approved != approved:
            raise ValidationError("A financial decision is immutable.")
        return existing
    if not reason.strip():
        raise ValidationError("An approval/rejection reason is required.")
    value = Decimal(0)
    journal = None
    if approved:
        if request.invoice_id and Journal.objects.filter(reversal_of=request.invoice.journal_id).exists():
            raise ValidationError("A reversed invoice cannot receive new adjustments.")
        if not request.effective_from <= on_date <= request.effective_to:
            raise ValidationError("Posting date is outside the request's effective period.")
        value = (
            request.value
            if request.mode == "fixed"
            else (request.invoice.amount * request.value / 100).quantize(
                Decimal(1).scaleb(-request.currency.decimal_places), rounding=ROUND_HALF_UP
            )
        )
        value = amount(value, request.currency)
        if value <= 0:
            raise ValidationError("The calculated benefit rounds to zero.")
        if request.kind == "refund":
            from .workflows import active_allocations, payment_state

            if payment_state(request.payment) != "confirmed":
                raise ValidationError("Original payment is no longer confirmed.")
            used = sum(
                active_allocations().filter(decision__payment=request.payment).values_list("amount", flat=True),
                Decimal(0),
            )
            if value > request.payment.amount - used - payment_refund_reservations(request.payment):
                raise ValidationError("Refund exceeds remaining unallocated credit from the original payment.")
            available = credit_available(request.student_account, request.currency, request.receivable_account)
            reserved = reserved_refunds(request.student_account, request.currency, request.receivable_account)
            if value > available - reserved:
                raise ValidationError("Refund exceeds unreserved student credit in this currency/control account.")
        else:
            if request.kind != "debit" and value > invoice_outstanding(request.invoice):
                raise ValidationError(
                    "Reduction exceeds current unpaid invoice debt; paid invoices cannot be silently discounted."
                )
            debit = request.kind == "debit"
            journal = post_journal(
                member=member,
                reference=number("ADJ"),
                idempotency_key=f"control:{request.pk}",
                date=on_date,
                period=period,
                currency=request.currency,
                description=f"{request.kind}: {request.reason}"[:500],
                source="invoice_adjustment",
                source_reference=request.number,
                lines=[
                    {
                        "account": request.receivable_account,
                        "student_account": request.student_account,
                        "debit" if debit else "credit": value,
                    },
                    {"account": request.counter_account, "credit" if debit else "debit": value},
                ],
            )
            with document_write():
                InvoiceAdjustment.objects.create(
                    invoice=request.invoice,
                    request=request,
                    journal=journal,
                    direction="debit" if debit else "credit",
                    amount=value,
                )
    with document_write():
        decision = FinanceDecision.objects.create(
            request=request, approved=approved, actor=member, reason=reason, amount=value, journal=journal
        )
    audit.record(
        "finance.control_approved" if approved else "finance.control_rejected",
        actor=member.user,
        obj=decision,
        reference=request.number,
        reason=reason,
        amount=value,
        effective_date=on_date,
    )
    return decision


@transaction.atomic
def disburse_refund(*, member, request, on_date, period, reference):
    member = lock(member, "finance.post")
    reference = reference.strip().upper()
    request = _scope(FinanceRequest, request)
    decision = FinanceDecision.objects.filter(request=request, approved=True).first()
    if request.kind != "refund" or not decision:
        raise ValidationError("An approved refund request is required.")
    if RefundClosure.objects.filter(decision=decision).exists():
        raise ValidationError("This refund approval is closed. Original disbursement/reversal history is retained.")
    if member.user_id == decision.actor.user_id:
        raise PermissionDenied("The refund approver cannot record their own disbursement.")
    existing = RefundDisbursement.objects.filter(decision=decision).first()
    if existing:
        if existing.reference != reference or existing.date != on_date:
            raise ValidationError("Refund has already been disbursed using different details.")
        return existing
    from .workflows import payment_state

    if payment_state(request.payment) != "confirmed":
        raise ValidationError("Original payment is no longer confirmed; refund cannot be disbursed.")
    if not request.effective_from <= on_date <= request.effective_to or on_date < request.payment.date:
        raise ValidationError("Disbursement must fall in the authorised period and not precede the original payment.")
    from .workflows import active_allocations

    used = sum(
        active_allocations().filter(decision__payment=request.payment).values_list("amount", flat=True), Decimal(0)
    )
    if decision.amount > request.payment.amount - used - payment_refund_reservations(request.payment, decision.pk):
        raise ValidationError("The approved source payment credit is no longer available.")
    if not reference.strip():
        raise ValidationError("An actual disbursement evidence/reference is required.")
    if request.counter_account.purpose == "cash":
        from .operations import ensure_cash_open

        ensure_cash_open(member, on_date, request.currency, request.counter_account)
    journal = post_journal(
        member=member,
        reference=number("REF"),
        idempotency_key=f"refund:{request.pk}",
        date=on_date,
        period=period,
        currency=request.currency,
        description=f"Refund disbursement {request.number}",
        source="refund_disbursement",
        source_reference=request.number,
        lines=[
            {
                "account": request.receivable_account,
                "student_account": request.student_account,
                "debit": decision.amount,
            },
            {"account": request.counter_account, "credit": decision.amount},
        ],
    )
    with document_write():
        result = RefundDisbursement.objects.create(
            decision=decision, journal=journal, actor=member, reference=reference, date=on_date
        )
    audit.record(
        "finance.refund_disbursed", actor=member.user, obj=result, reference=reference, control_reference=request.number
    )
    return result


@transaction.atomic
def reverse_control(*, member, request, on_date, period, reason):
    member = lock(member, "finance.approve")
    request = _scope(FinanceRequest, request)
    if request.kind == "refund":
        return close_refund(member=member, request=request, on_date=on_date, period=period, reason=reason)
    decision = FinanceDecision.objects.filter(request=request, approved=True, journal__isnull=False).first()
    if not decision:
        raise ValidationError("A posted invoice adjustment is required.")
    if member.user_id in (request.requester.user_id, decision.actor.user_id):
        raise PermissionDenied("A separate approver must reverse this adjustment.")
    existing = Journal.objects.filter(reversal_of=decision.journal).first()
    if existing:
        return existing
    adjustment = InvoiceAdjustment.objects.get(request=request)
    if adjustment.direction == "debit" and invoice_outstanding(request.invoice) < adjustment.amount:
        raise ValidationError("Reverse the associated payment allocations before reducing a paid debit adjustment.")
    result = reverse_journal(
        decision.journal,
        member=member,
        reference=number("REV"),
        idempotency_key=f"control-reverse:{request.pk}",
        date=on_date,
        period=period,
        reason=reason,
    )
    audit.record("finance.control_reversed", actor=member.user, obj=result, reference=request.number, reason=reason)
    return result


@transaction.atomic
def close_refund(*, member, request, on_date, period, reason):
    member = lock(member, "finance.approve")
    request = _scope(FinanceRequest, request)
    decision = FinanceDecision.objects.filter(request=request, approved=True).first()
    if request.kind != "refund" or not decision or not reason.strip():
        raise ValidationError("An approved refund and a cancellation/correction reason are required.")
    if member.user_id in (request.requester.user_id, decision.actor.user_id):
        raise PermissionDenied("A different approver must cancel or reverse this refund authorisation.")
    existing = RefundClosure.objects.filter(decision=decision).first()
    if existing:
        return existing
    disbursement = RefundDisbursement.objects.filter(decision=decision).first()
    journal = None
    if disbursement:
        if member.user_id == disbursement.actor.user_id:
            raise PermissionDenied("A refund cashier cannot approve reversal of their own disbursement.")
        journal = Journal.objects.filter(reversal_of=disbursement.journal).first()
        if not journal:
            journal = reverse_journal(
                disbursement.journal,
                member=member,
                reference=number("REV"),
                idempotency_key=f"refund-reverse:{request.pk}",
                date=on_date,
                period=period,
                reason=reason,
            )
    with document_write():
        result = RefundClosure.objects.create(decision=decision, actor=member, reason=reason, journal=journal)
    audit.record(
        "finance.refund_closed",
        actor=member.user,
        obj=result,
        control_reference=request.number,
        reason=reason,
        disbursement_reversed=bool(disbursement),
    )
    return result
