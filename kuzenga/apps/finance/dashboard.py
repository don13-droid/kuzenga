"""Currency-separated dashboard definitions; all amounts derive from posted school records."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from apps.academics.models import AcademicYear, Term
from apps.students.models import StudentEnrolment

from .models import (
    CashSubmission,
    Currency,
    FinanceDecision,
    FinanceImport,
    FinanceRequest,
    Invoice,
    Payment,
    ReconciledEntry,
    ReconciliationMatch,
    RefundDisbursement,
    StatementRow,
)
from .services import _scope, authorize
from .workflows import active_allocations, debt_rows, invoice_balance_map, student_debt_balances


def dashboard(member, *, academic_year=None, term=None, currency=None, start=None, end=None):
    authorize(member, "finance.view")
    today = timezone.localdate()
    end = end or today
    year = _scope(AcademicYear, academic_year) if academic_year else None
    selected = _scope(Term, term) if term else None
    if year and selected and selected.academic_year_id != year.pk:
        raise ValidationError("Selected term belongs to another academic year.")
    for period in (year, selected):
        if period:
            start = max(start, period.start_date) if start else period.start_date
            end = min(end, period.end_date)
    if start and end < start:
        raise ValidationError("Selected date ranges do not overlap.")
    currencies = list(Currency.objects.filter(pk=_scope(Currency, currency).pk) if currency else Currency.objects.all())
    totals = {
        c.pk: {
            "currency": c,
            **{
                key: Decimal(0)
                for key in [
                    "billed",
                    "net_billed",
                    "collected",
                    "refunds",
                    "outstanding",
                    "overdue",
                    "daily",
                    "term",
                    "unallocated",
                    "shortages",
                    "overages",
                    "cohort_paid",
                    "student_credit",
                ]
            },
        }
        for c in currencies
    }
    invoices = Invoice.objects.filter(currency__in=currencies, issue_date__lte=end).select_related(
        "journal__reversal", "fee"
    )
    if start:
        invoices = invoices.filter(issue_date__gte=start)
    if year:
        invoices = invoices.filter(fee__academic_year=year)
    if selected:
        invoices = invoices.filter(Q(fee__term=selected) | Q(fee__term__isnull=True))
    invoices = list(invoices)
    amounts = invoice_balance_map(invoices, end)
    for invoice in invoices:
        reversal = getattr(invoice.journal, "reversal", None)
        if reversal and reversal.date <= end:
            continue
        row = totals[invoice.currency_id]
        row["billed"] += invoice.amount
        row["net_billed"] += amounts[invoice.pk]["outstanding"] + amounts[invoice.pk]["paid"]
        row["cohort_paid"] += amounts[invoice.pk]["paid"]
    owed = debt_rows(member, currency=currency, on_date=end)
    ageing = defaultdict(lambda: Decimal(0))
    for item in owed:
        cid = item["invoice"].currency_id
        if cid in totals:
            if item["days"]:
                totals[cid]["overdue"] += item["outstanding"]
            ageing[(item["invoice"].currency.code, item["bucket"])] += item["outstanding"]
    debtors = student_debt_balances(member, currency=currency, on_date=end)
    students = {row["account"].student_id for row in debtors}
    placements = (
        StudentEnrolment.objects.filter(
            student_id__in=students,
            effective_from__lte=end,
            class_group__academic_year__start_date__lte=end,
            class_group__academic_year__end_date__gte=end,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=end))
        .select_related("class_group__grade")
        .order_by("effective_from")
    )
    classes = {p.student_id: p.class_group for p in placements}
    by_class = defaultdict(lambda: Decimal(0))
    for row in debtors:
        if row["currency"].pk not in totals:
            continue
        totals[row["currency"].pk]["outstanding"] += max(Decimal(0), row["balance"])
        totals[row["currency"].pk]["student_credit"] += max(Decimal(0), -row["balance"])
        if row["balance"] > 0:
            cls = classes.get(row["account"].student_id)
            by_class[
                (
                    row["currency"].code,
                    cls.grade.name if cls else "Historical / no current grade",
                    cls.name if cls else "No current class",
                )
            ] += row["balance"]
    allocated = defaultdict(lambda: Decimal(0))
    for pid, value in active_allocations(end).values_list("decision__payment_id", "amount").iterator():
        allocated[pid] += value
    refunded = defaultdict(lambda: Decimal(0))
    for payment_id, value, refund_date, cid in (
        RefundDisbursement.objects.filter(date__lte=end)
        .filter(Q(journal__reversal__isnull=True) | Q(journal__reversal__date__gt=end))
        .values_list("decision__request__payment_id", "decision__amount", "date", "decision__request__currency_id")
    ):
        refunded[payment_id] += value
        if cid in totals and (not start or refund_date >= start):
            totals[cid]["refunds"] += value
    term_period = selected or Term.objects.filter(is_current=True).first()
    methods, months = defaultdict(lambda: Decimal(0)), defaultdict(lambda: Decimal(0))
    payments = Payment.objects.filter(currency__in=currencies).select_related("decision__journal__reversal", "currency")
    for payment in payments:
        decision = getattr(payment, "decision", None)
        journal = decision.journal if decision and decision.journal_id else None
        if not journal or journal.date > end:
            continue
        reversal = getattr(journal, "reversal", None)
        if reversal and reversal.date <= end:
            continue
        row = totals[payment.currency_id]
        row["unallocated"] += max(Decimal(0), payment.amount - allocated[payment.pk] - refunded[payment.pk])
        if start and payment.date < start:
            continue
        row["collected"] += payment.amount
        if payment.date == today:
            row["daily"] += payment.amount
        if term_period and term_period.start_date <= payment.date <= term_period.end_date:
            row["term"] += payment.amount
        methods[(payment.currency.code, payment.get_method_display())] += payment.amount
        months[(payment.currency.code, payment.date.strftime("%Y-%m"))] += payment.amount
    for submission in CashSubmission.objects.filter(
        session__currency__in=currencies, session__date__lte=end
    ).select_related("session"):
        if start and submission.session.date < start:
            continue
        row = totals[submission.session.currency_id]
        row["shortages"] += max(Decimal(0), -submission.difference)
        row["overages"] += max(Decimal(0), submission.difference)
    for row in totals.values():
        row["collection_rate"] = (
            (row["cohort_paid"] * 100 / row["net_billed"]).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
            if row["net_billed"] > 0
            else None
        )
    # Operational counts are explicitly school-wide/current, not currency-valued totals.
    pending = FinanceRequest.objects.filter(decision__isnull=True).count()
    pending += CashSubmission.objects.filter(review__isnull=True).count()
    pending += ReconciliationMatch.objects.filter(decision__isnull=True).count()
    pending += FinanceImport.objects.filter(decision__isnull=True).count()
    active_matches = ReconciledEntry.objects.filter(release__isnull=True)
    exceptions = StatementRow.objects.exclude(pk__in=active_matches.values("row_id")).count()
    exceptions += active_matches.filter(line__journal__reversal__isnull=False).count()
    exceptions += sum(len(batch.errors) for batch in FinanceImport.objects.filter(kind="statement", decision__isnull=True))
    pending_refunds = FinanceDecision.objects.filter(
        approved=True,
        request__kind="refund",
        disbursement__isnull=True,
        closure__isnull=True,
    ).count()
    return {
        "totals": list(totals.values()),
        "ageing": sorted(ageing.items()),
        "by_class": sorted(by_class.items()),
        "methods": sorted(methods.items()),
        "months": sorted(months.items()),
        "pending": pending,
        "exceptions": exceptions,
        "pending_refunds": pending_refunds,
        "as_of": end,
        "term_label": str(term_period) if term_period else "No selected/current term configured",
    }
