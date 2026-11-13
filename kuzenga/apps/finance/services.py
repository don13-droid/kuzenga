"""Authorised posting is the sole application write boundary for the ledger."""

import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction

from apps.core import audit
from apps.core.context import get_current_tenant
from apps.tenancy.models import Membership, Tenant
from apps.tenancy.permissions import has_permission
from apps.tenancy.services import has_module

from .models import Account, AccountingPeriod, Currency, Journal, JournalLine, StudentAccount, _ledger_write


def authorize(member, permission):
    tenant = get_current_tenant()
    if tenant is None or member is None:
        raise PermissionDenied
    # Re-read authority: stale/suspended memberships must not post from service callers.
    current = (
        Membership.objects.select_related("user")
        .filter(pk=member.pk, tenant=tenant, status="active", user__is_active=True)
        .first()
    )
    if (
        not current
        or current.user.is_superuser
        or not has_permission(current, permission)
        or not has_module(tenant, "finance")
    ):
        raise PermissionDenied
    return current


def amount(value, currency):
    if isinstance(value, (float, bool)):
        raise ValidationError("Supply financial amounts as Decimal or decimal strings, never floats.")
    try:
        result = Decimal(value)
        unit = Decimal(1).scaleb(-currency.decimal_places)
        if not result.is_finite() or result < 0 or result != result.quantize(unit) or result >= Decimal("100000000000"):
            raise ValidationError("Amount is negative, nonfinite, too large or exceeds currency precision.")
        return result.quantize(unit)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("Invalid financial amount.") from exc


def _scope(model, value):
    key = getattr(value, "pk", value)
    try:
        return model.objects.get(pk=key)
    except (model.DoesNotExist, ValidationError, ValueError, TypeError) as exc:
        raise ValidationError("Select an available record from the active school.") from exc


@transaction.atomic
def configure(model, data, member):
    from .models import FeeRule

    member = authorize(member, "finance.fees" if model is FeeRule else "finance.configure")
    Tenant.objects.select_for_update().get(pk=member.tenant_id)

    if model not in (Currency, Account, AccountingPeriod, FeeRule):
        raise ValidationError("Unsupported financial configuration.")
    obj = model(tenant_id=member.tenant_id, **data)
    obj.save()
    audit.record("finance.configuration_created", actor=member.user, obj=obj)
    return obj


@transaction.atomic
def student_account(student, member):
    member = authorize(member, "finance.post")
    Tenant.objects.select_for_update().get(pk=member.tenant_id)
    from apps.students.models import Student

    student = _scope(Student, student)
    result, created = StudentAccount.objects.get_or_create(student=student)
    if created:
        audit.record("finance.student_account_created", actor=member.user, obj=result)
    return result


@transaction.atomic
def post_journal(
    *,
    member,
    reference,
    idempotency_key,
    date,
    period,
    currency,
    description,
    source,
    source_reference,
    lines,
    reversal_of=None,
    exchange_rate=None,
    rate_effective_date=None,
    rate_reference="",
):
    member = authorize(
        member,
        "finance.approve" if reversal_of or source in ("invoice_adjustment", "opening_import") else "finance.post",
    )
    Tenant.objects.select_for_update().get(pk=member.tenant_id)
    currency, period = _scope(Currency, currency), _scope(AccountingPeriod, period)
    if (
        not reference.strip()
        or not idempotency_key.strip()
        or not description.strip()
        or not source.strip()
        or not source_reference.strip()
    ):
        raise ValidationError("Reference, idempotency key, description and source details are required.")
    prepared = []
    for line in lines:
        account = _scope(Account, line["account"])
        student = _scope(StudentAccount, line["student_account"]) if line.get("student_account") else None
        debit, credit = amount(line.get("debit", "0"), currency), amount(line.get("credit", "0"), currency)
        if (debit > 0) == (credit > 0):
            raise ValidationError("Each journal line needs exactly one positive debit or credit.")
        if (account.purpose == "receivable") != bool(student):
            raise ValidationError("Student receivable lines require a student account; other lines must not have one.")
        prepared.append(
            {
                "account": account,
                "student_account": student,
                "debit": debit,
                "credit": credit,
                "description": line.get("description", ""),
            }
        )
    if (
        len(prepared) < 2
        or len(prepared) > 1000
        or sum(x["debit"] for x in prepared) != sum(x["credit"] for x in prepared)
    ):
        raise ValidationError("A journal requires 2–1000 lines and equal debit and credit totals.")
    original = _scope(Journal, reversal_of) if reversal_of else None
    payload = {
        "reference": reference,
        "date": str(date),
        "period": str(period.pk),
        "currency": str(currency.pk),
        "description": description,
        "source": source,
        "source_reference": source_reference,
        "reversal": str(original.pk) if original else None,
        "rate": str(exchange_rate),
        "rate_date": str(rate_effective_date),
        "rate_reference": rate_reference,
        "lines": [{k: str(getattr(v, "pk", v)) for k, v in line.items()} for line in prepared],
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = Journal.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.fingerprint != fingerprint or not existing.posted:
            raise ValidationError("Idempotency key conflicts with another request.")
        return existing
    for line in prepared:
        if line["account"].purpose == "cash" and source != "student_payment":
            from .operations import ensure_cash_open

            cashier = original.created_by if original else member
            if original and original.source == "student_payment":
                from .models import PaymentDecision

                posting = (
                    PaymentDecision.objects.filter(journal=original).select_related("payment__recorded_by").first()
                )
                if posting:
                    cashier = posting.payment.recorded_by
            ensure_cash_open(cashier, date, currency, line["account"])
    if not currency.is_active or period.closed or not period.starts_on <= date <= period.ends_on:
        raise ValidationError("Choose an active currency and an open period containing the transaction date.")
    if any(not line["account"].is_active for line in prepared):
        raise ValidationError("Inactive accounts cannot receive postings.")
    if exchange_rate is not None:
        if isinstance(exchange_rate, float):
            raise ValidationError("Exchange rates must use Decimal.")
        try:
            exchange_rate = Decimal(exchange_rate)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError("Invalid exchange rate.") from exc
        if not exchange_rate.is_finite() or exchange_rate <= 0 or not rate_effective_date or not rate_reference:
            raise ValidationError("Positive exchange rate, effective date and source reference are required.")
    elif rate_effective_date or rate_reference:
        raise ValidationError("Exchange metadata requires an explicit rate.")
    if original:
        if original.created_by.user_id == member.user_id:
            raise PermissionDenied("Another authorised person must approve the reversal.")
        expected = sorted(
            (str(line.account_id), str(line.student_account_id), line.credit, line.debit)
            for line in original.lines.all()
        )
        actual = sorted(
            (
                str(line["account"].pk),
                str(line["student_account"].pk) if line["student_account"] else "None",
                line["debit"],
                line["credit"],
            )
            for line in prepared
        )
        if not original.posted or original.currency_id != currency.pk or expected != actual:
            raise ValidationError("Reversal must exactly offset the original journal in its currency.")
    marker = _ledger_write.set(True)
    try:
        journal = Journal.objects.create(
            reference=reference,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            date=date,
            period=period,
            currency=currency,
            description=description,
            source=source,
            source_reference=source_reference,
            created_by=member,
            reversal_of=original,
            exchange_rate=exchange_rate,
            rate_effective_date=rate_effective_date,
            rate_reference=rate_reference,
        )
        for line in prepared:
            JournalLine.objects.create(journal=journal, **line)
        # Explicit internal lifecycle transition. DB triggers validate balance and freeze the rows.
        models.QuerySet.update(Journal.objects.filter(pk=journal.pk, posted=False), posted=True)
        journal.refresh_from_db()
    finally:
        _ledger_write.reset(marker)
    audit.record(
        "finance.journal_reversed" if original else "finance.journal_posted",
        actor=member.user,
        obj=journal,
        reference=reference,
        source=source,
        source_reference=source_reference,
        reversal_of=original.pk if original else "",
        changes={"posted": {"before": False, "after": True}},
    )
    return journal


def reverse_journal(original, *, member, reference, idempotency_key, date, period, reason):
    authorize(member, "finance.approve")
    original = _scope(Journal, original)
    if not reason.strip():
        raise ValidationError("A reversal reason is required.")
    return post_journal(
        member=member,
        reference=reference,
        idempotency_key=idempotency_key,
        date=date,
        period=period,
        currency=original.currency,
        description=reason,
        source="reversal",
        source_reference=original.reference,
        reversal_of=original,
        exchange_rate=original.exchange_rate,
        rate_effective_date=original.rate_effective_date,
        rate_reference=original.rate_reference,
        lines=[
            {
                "account": line.account,
                "student_account": line.student_account,
                "debit": line.credit,
                "credit": line.debit,
                "description": line.description,
            }
            for line in original.lines.select_related("account", "student_account")
        ],
    )


def balances(member, student=None):
    authorize(member, "finance.view")
    qs = JournalLine.objects.filter(journal__posted=True)
    if student is not None:
        student = _scope(StudentAccount, student)
        qs = qs.filter(student_account=student)
    totals = {}
    for code, debit, credit in qs.values_list("journal__currency__code", "debit", "credit").iterator(chunk_size=500):
        totals[code] = totals.get(code, Decimal(0)) + debit - credit
    return totals


def ledger_totals(queryset, by_account=False):
    """Sum retrieved Decimal amounts exactly; SQLite SUM uses binary floating point."""
    groups = {}
    for code, account_code, account_name, debit, credit in queryset.values_list(
        "journal__currency__code", "account__code", "account__name", "debit", "credit"
    ).iterator(chunk_size=500):
        key = (code, account_code) if by_account else (code,)
        row = groups.setdefault(
            key,
            {
                "journal__currency__code": code,
                "account__code": account_code,
                "account__name": account_name,
                "debits": Decimal(0),
                "credits": Decimal(0),
            },
        )
        row["debits"] += debit
        row["credits"] += credit
    return [groups[key] for key in sorted(groups)]
