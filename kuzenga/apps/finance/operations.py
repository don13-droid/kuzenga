"""Cash-up, reviewed CSV imports and reconciliation; no external payments or notifications."""

import csv
import hashlib
import io
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from apps.core import audit
from apps.students.models import Student

from .models import (
    Account,
    CashReview,
    CashSession,
    CashSubmission,
    Currency,
    FinanceImport,
    ImportDecision,
    Journal,
    JournalLine,
    MatchDecision,
    OpeningEntry,
    PaymentDecision,
    ReconciledEntry,
    ReconciliationMatch,
    RefundDisbursement,
    StatementRow,
    StudentAccount,
)
from .services import _scope, amount, post_journal
from .workflows import document_write, lock, number


def ensure_cash_open(cashier, on_date, currency, account):
    if CashSession.objects.filter(
        cashier=cashier, date=on_date, currency=currency, account=account, submission__isnull=False
    ).exists():
        raise ValidationError("This cashier's cash-up is submitted; do not backdate cash postings into the closed day.")


@transaction.atomic
def open_cash(*, member, on_date, currency, account, opening_float):
    member = lock(member, "finance.post")
    currency, account = _scope(Currency, currency), _scope(Account, account)
    opening_float = amount(opening_float, currency)
    if account.kind != "asset" or account.purpose != "cash" or not account.is_active:
        raise ValidationError("Select an active cash asset account.")
    existing = CashSession.objects.filter(cashier=member, date=on_date, currency=currency, account=account).first()
    if existing:
        if existing.opening_float != opening_float:
            raise ValidationError("A cash session already exists with a different opening float.")
        return existing
    with document_write():
        result = CashSession.objects.create(
            cashier=member, date=on_date, currency=currency, account=account, opening_float=opening_float
        )
    audit.record("finance.cash_session_opened", actor=member.user, obj=result, date=on_date)
    return result


def cash_expected(session):
    expected = session.opening_float
    # Use original cashier attribution, including subsequent reversal journals on this day.
    for decision in PaymentDecision.objects.filter(
        payment__recorded_by=session.cashier,
        payment__method="cash",
        payment__currency=session.currency,
        payment__receiving_account=session.account,
        journal__isnull=False,
    ).select_related("journal__reversal", "payment"):
        if decision.journal.date == session.date:
            expected += decision.payment.amount
        reversal = getattr(decision.journal, "reversal", None)
        if reversal and reversal.date == session.date:
            expected -= decision.payment.amount
    for refund in RefundDisbursement.objects.filter(
        actor=session.cashier,
        decision__request__currency=session.currency,
        decision__request__counter_account=session.account,
    ).select_related("decision", "journal__reversal"):
        if refund.date == session.date:
            expected -= refund.decision.amount
        reversal = getattr(refund.journal, "reversal", None)
        if reversal and reversal.date == session.date:
            expected += refund.decision.amount
    manual = JournalLine.objects.filter(
        account=session.account, journal__currency=session.currency, journal__date=session.date, journal__posted=True
    ).exclude(journal__source__in=["student_payment", "refund_disbursement"])
    manual = manual.filter(
        Q(journal__created_by=session.cashier, journal__reversal_of__isnull=True)
        | Q(journal__reversal_of__created_by=session.cashier)
    ).exclude(journal__reversal_of__source__in=["student_payment", "refund_disbursement"])
    expected += sum((debit - credit for debit, credit in manual.values_list("debit", "credit")), Decimal(0))
    return expected


@transaction.atomic
def submit_cash(*, member, session, actual, note):
    member = lock(member, "finance.post")
    session = _scope(CashSession, session)
    if session.cashier.user_id != member.user_id:
        raise PermissionDenied("Only the session's cashier may submit the cash count.")
    actual = amount(actual, session.currency)
    existing = CashSubmission.objects.filter(session=session).first()
    if existing:
        if existing.actual != actual or existing.note != note:
            raise ValidationError("Submitted cash-up figures cannot change.")
        return existing
    expected = cash_expected(session)
    if actual != expected and not note.strip():
        raise ValidationError("Explain every shortage or overage.")
    with document_write():
        result = CashSubmission.objects.create(
            session=session, expected=expected, actual=actual, difference=actual - expected, note=note
        )
    audit.record(
        "finance.cash_up_submitted",
        actor=member.user,
        obj=result,
        expected=expected,
        actual=actual,
        difference=actual - expected,
    )
    return result


@transaction.atomic
def review_cash(*, member, submission, approved, reason):
    member = lock(member, "finance.approve")
    submission = _scope(CashSubmission, submission)
    if submission.session.cashier.user_id == member.user_id:
        raise PermissionDenied("A separate supervisor must review cash-up.")
    if not reason.strip():
        raise ValidationError("A review reason is required.")
    existing = CashReview.objects.filter(submission=submission).first()
    if existing:
        if existing.approved != approved:
            raise ValidationError("Cash-up review history is immutable.")
        return existing
    with document_write():
        result = CashReview.objects.create(submission=submission, actor=member, approved=approved, reason=reason)
    audit.record("finance.cash_up_reviewed", actor=member.user, obj=result, approved=approved, reason=reason)
    return result


def signed_amount(value, currency):
    try:
        parsed = Decimal(value)
        if not parsed.is_finite() or parsed == 0:
            raise ValidationError("Amounts must be finite and nonzero.")
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Invalid signed amount.") from exc
    return amount(abs(parsed), currency) * (-1 if parsed < 0 else 1)


def parse_rows(kind, source, account=None, currency=None):
    reader = csv.DictReader(io.StringIO(source))
    required = (
        {"date", "reference", "amount"}
        if kind == "statement"
        else {"student_reference", "currency", "amount", "reference"}
    )
    if (
        not reader.fieldnames
        or not required.issubset(reader.fieldnames)
        or len(reader.fieldnames) != len(set(reader.fieldnames))
    ):
        raise ValidationError("CSV requires unique columns: " + ", ".join(sorted(required)))
    rows, errors, seen = [], [], set()
    for index, raw in enumerate(reader, 2):
        if index > 501:
            raise ValidationError("Import at most 500 rows per reviewed batch.")
        try:
            reference = (raw.get("reference") or "").strip()
            if not reference or len(reference) > 100:
                raise ValidationError("A source reference of at most 100 characters is required.")
            if kind == "statement":
                if raw.get("currency") and raw["currency"].strip().upper() != currency.code:
                    raise ValidationError("Statement row currency differs from the selected currency.")
                try:
                    on_date = date.fromisoformat((raw.get("date") or "").strip())
                except (TypeError, ValueError) as exc:
                    raise ValidationError("Use an ISO date (YYYY-MM-DD).") from exc
                value = signed_amount(raw["amount"], currency)
                fingerprint = hashlib.sha256(
                    json.dumps([str(account.pk), str(currency.pk), str(on_date), reference, str(value)]).encode()
                ).hexdigest()
                if fingerprint in seen or StatementRow.objects.filter(fingerprint=fingerprint).exists():
                    raise ValidationError("Duplicate statement transaction, including overlapping prior imports.")
                seen.add(fingerprint)
                rows.append(
                    {"date": str(on_date), "reference": reference, "amount": str(value), "fingerprint": fingerprint}
                )
            else:
                student = Student.objects.filter(admission_number=(raw.get("student_reference") or "").strip()).first()
                chosen = Currency.objects.filter(
                    code=(raw.get("currency") or "").strip().upper(), is_active=True
                ).first()
                if not student or not chosen:
                    raise ValidationError(
                        "Student reference or configured active currency was not found in this school."
                    )
                value = signed_amount(raw["amount"], chosen)
                key = (student.pk, chosen.pk)
                if (
                    key in seen
                    or OpeningEntry.objects.filter(student_account__student=student, currency=chosen).exists()
                ):
                    raise ValidationError("Opening balance already exists for this student/currency.")
                seen.add(key)
                rows.append(
                    {
                        "student": str(student.pk),
                        "admission": student.admission_number,
                        "name": student.full_name,
                        "currency": str(chosen.pk),
                        "code": chosen.code,
                        "amount": str(value),
                        "reference": reference,
                    }
                )
        except ValidationError as exc:
            errors.append({"row": index, "error": " ".join(exc.messages)})
    if not rows and not errors:
        raise ValidationError("The CSV contains no data rows.")
    return rows, errors


@transaction.atomic
def preview_import(*, member, kind, source, source_name, account=None, currency=None, receivable=None, offset=None):
    member = lock(member, "finance.post")
    if kind not in ("opening", "statement") or len(source.encode("utf-8")) > 1_000_000:
        raise ValidationError("Select a valid import type and a UTF-8 CSV no larger than 1 MB.")
    if kind == "statement":
        account, currency = _scope(Account, account), _scope(Currency, currency)
        if account.kind != "asset" or account.purpose not in ("bank", "mobile_clearing") or not account.is_active:
            raise ValidationError("Select an active bank or mobile-money asset account.")
    else:
        receivable, offset = _scope(Account, receivable), _scope(Account, offset)
        if receivable.purpose != "receivable" or offset.purpose != "opening" or offset.kind != "equity":
            raise ValidationError("Opening imports need a receivable asset and opening-funds equity account.")
    source = source.lstrip("\ufeff")
    digest = hashlib.sha256(
        json.dumps(
            [
                kind,
                str(getattr(account, "pk", "")),
                str(getattr(currency, "pk", "")),
                str(getattr(receivable, "pk", "")),
                str(getattr(offset, "pk", "")),
                source,
            ]
        ).encode()
    ).hexdigest()
    existing = FinanceImport.objects.filter(digest=digest).first()
    if existing:
        return existing
    try:
        rows, errors = parse_rows(kind, source, account, currency)
    except csv.Error as exc:
        raise ValidationError("CSV contains malformed or oversized fields.") from exc
    with document_write():
        result = FinanceImport.objects.create(
            kind=kind,
            source=source,
            source_name=source_name.replace("\\", "/").split("/")[-1][:100],
            digest=digest,
            account=account if kind == "statement" else None,
            currency=currency if kind == "statement" else None,
            receivable=receivable if kind == "opening" else None,
            offset=offset if kind == "opening" else None,
            rows=rows,
            errors=errors,
            requester=member,
        )
    audit.record(
        "finance.import_previewed",
        actor=member.user,
        obj=result,
        kind=kind,
        rows=len(rows),
        invalid=len(errors),
        digest=digest,
    )
    return result


@transaction.atomic
def decide_import(*, member, batch, approved, reason, period=None, on_date=None, acknowledged_existing=False):
    member = lock(member, "finance.approve")
    batch = _scope(FinanceImport, batch)
    if batch.requester.user_id == member.user_id:
        raise PermissionDenied("A separate approver must review imported balances/statements.")
    existing = ImportDecision.objects.filter(batch=batch).first()
    if existing:
        if existing.approved != approved:
            raise ValidationError("Import decisions cannot change.")
        return existing
    if not reason.strip():
        raise ValidationError("A review reason is required.")
    if approved:
        try:
            rows, errors = parse_rows(batch.kind, batch.source, batch.account, batch.currency)
        except csv.Error as exc:
            raise ValidationError("CSV contains malformed or oversized fields.") from exc
        if errors or batch.errors or rows != batch.rows:
            raise ValidationError(
                "Resolve all import exceptions in a new reviewed CSV; this source is preserved unchanged."
            )
        for row in rows:
            if batch.kind == "statement":
                with document_write():
                    StatementRow.objects.create(
                        batch=batch,
                        account=batch.account,
                        currency=batch.currency,
                        date=date.fromisoformat(row["date"]),
                        reference=row["reference"],
                        amount=Decimal(row["amount"]),
                        fingerprint=row["fingerprint"],
                    )
            else:
                student, currency = _scope(Student, row["student"]), _scope(Currency, row["currency"])
                account, created = StudentAccount.objects.get_or_create(student=student)
                if created:
                    audit.record(
                        "finance.student_account_created", actor=member.user, obj=account, source="opening_import"
                    )
                if (
                    not acknowledged_existing
                    and JournalLine.objects.filter(student_account=account, journal__currency=currency).exists()
                ):
                    raise ValidationError(
                        "Existing ledger activity requires explicit acknowledgement: opening entries add to, never overwrite, balances."
                    )
                value = Decimal(row["amount"])
                journal = post_journal(
                    member=member,
                    reference=number("OPEN"),
                    idempotency_key=f"opening:{account.pk}:{currency.pk}",
                    date=on_date,
                    period=period,
                    currency=currency,
                    description=f"Imported opening balance {row['reference']}",
                    source="opening_import",
                    source_reference=str(batch.pk),
                    lines=[
                        {
                            "account": batch.receivable,
                            "student_account": account,
                            "debit" if value > 0 else "credit": abs(value),
                        },
                        {"account": batch.offset, "credit" if value > 0 else "debit": abs(value)},
                    ],
                )
                with document_write():
                    OpeningEntry.objects.create(
                        batch=batch,
                        student_account=account,
                        currency=currency,
                        reference=row["reference"],
                        amount=value,
                        journal=journal,
                    )
    with document_write():
        decision = ImportDecision.objects.create(
            batch=batch, actor=member, approved=approved, reason=reason, acknowledged_existing=acknowledged_existing
        )
    audit.record(
        "finance.import_approved" if approved else "finance.import_rejected",
        actor=member.user,
        obj=decision,
        kind=batch.kind,
        rows=len(batch.rows),
        reason=reason,
    )
    return decision


def validate_match(row, line):
    if row.account_id != line.account_id or row.currency_id != line.journal.currency_id or not line.journal.posted:
        raise ValidationError("Reconciliation needs the same settlement account, currency and a posted journal.")
    if row.amount != line.debit - line.credit:
        raise ValidationError("Statement and ledger movement amounts must match exactly.")
    if ReconciledEntry.objects.filter(row=row, release__isnull=True).exists() or ReconciledEntry.objects.filter(line=line, release__isnull=True).exists():
        raise ValidationError("This statement or ledger transaction is already reconciled.")
    if Journal.objects.filter(reversal_of=line.journal_id).exists():
        raise ValidationError("A reversed ledger transaction requires exception review, not a new match.")


@transaction.atomic
def request_match(*, member, row, line, reason, idempotency_key):
    member = lock(member, "finance.post")
    row, line = _scope(StatementRow, row), _scope(JournalLine, line)
    existing = ReconciliationMatch.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.row_id != row.pk or existing.line_id != line.pk or existing.reason != reason:
            raise ValidationError("Match request key conflicts with another decision.")
        return existing
    validate_match(row, line)
    if not reason.strip():
        raise ValidationError("Document the matching evidence, including any date/reference differences.")
    with document_write():
        result = ReconciliationMatch.objects.create(
            row=row, line=line, reason=reason, requester=member, idempotency_key=idempotency_key
        )
    audit.record(
        "finance.reconciliation_requested",
        actor=member.user,
        obj=result,
        statement=row.reference,
        journal=line.journal.reference,
    )
    return result


@transaction.atomic
def decide_match(*, member, match, approved, reason):
    member = lock(member, "finance.approve")
    match = _scope(ReconciliationMatch, match)
    if match.requester.user_id == member.user_id:
        raise PermissionDenied("A different approver must review manual reconciliation.")
    existing = MatchDecision.objects.filter(match=match).first()
    if existing:
        if existing.approved != approved:
            raise ValidationError("Reconciliation decisions are immutable.")
        return existing
    if not reason.strip():
        raise ValidationError("A review reason is required.")
    if approved:
        validate_match(match.row, match.line)
    with document_write():
        result = MatchDecision.objects.create(match=match, actor=member, approved=approved, reason=reason)
        if approved:
            ReconciledEntry.objects.create(decision=result, row=match.row, line=match.line)
    audit.record(
        "finance.reconciliation_approved" if approved else "finance.reconciliation_rejected",
        actor=member.user,
        obj=result,
        reason=reason,
    )
    return result


@transaction.atomic
def release_match(*, member, entry, reason):
    from .models import ReconciliationRelease

    member = lock(member, "finance.approve")
    entry = _scope(ReconciledEntry, entry)
    if member.user_id in (entry.decision.actor.user_id, entry.decision.match.requester.user_id):
        raise PermissionDenied("A different approver must release an approved match.")
    if not reason.strip() or len(reason) > 1000:
        raise ValidationError("A correction reason of at most 1000 characters is required.")
    if ReconciliationRelease.objects.filter(entry=entry).exists():
        raise ValidationError("This match has already been released.")
    with document_write():
        release = ReconciliationRelease.objects.create(entry=entry, actor=member, reason=reason)
    audit.record("finance.reconciliation_released", actor=member.user, obj=release,
                 statement=entry.row.reference, journal=entry.line.journal.reference, reason=reason)
    return release
