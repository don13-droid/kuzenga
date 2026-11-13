"""Bounded, live finance exports. Currency codes accompany every monetary row."""

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.core.models import AuditEvent

from .models import JournalLine, Payment
from .services import authorize, ledger_totals
from .workflows import debt_rows, payment_state

LIMIT = 5000
KINDS = [
    (k, v)
    for k, v in {
        "collections": "Payment history",
        "cashiers": "Cashier collections",
        "methods": "Payment-method collections",
        "debt": "Debtors ageing",
        "ledger": "General ledger",
        "trial": "Trial balance / period movement",
        "audit": "Financial audit history",
        "cohorts": "Outstanding debt by grade and class",
    }.items()
]


def bounded(qs):
    values = list(qs[: LIMIT + 1])
    if len(values) > LIMIT:
        raise ValidationError("More than 5,000 source records: narrow the date or currency filters.")
    return values


def report_data(member, kind, currency=None, start=None, end=None):
    authorize(member, "finance.view")
    if kind not in dict(KINDS):
        raise ValidationError("Select a supported report.")
    if kind == "cohorts":
        from .dashboard import dashboard

        if JournalLine.objects.count() > LIMIT:
            raise ValidationError(
                "Cohort export supports up to 5,000 ledger lines; use the dashboard for larger cohorts."
            )
        data = dashboard(member, currency=currency, start=start, end=end)
        return ["Currency", "Grade", "Class", "Net outstanding as of end date"], [
            [*key, value] for key, value in data["by_class"]
        ]
    if kind == "debt":
        # Debt is as-of end; start limits the original invoice cohort only.
        from .models import Invoice

        if Invoice.objects.count() > LIMIT:
            raise ValidationError("Debtors export supports up to 5,000 invoices; use the paginated debt directory.")
        items = debt_rows(member, currency=currency, on_date=end)
        return ["Student", "Admission", "Invoice", "Currency", "Due", "Days overdue", "Age band", "Outstanding"], [
            [
                r["invoice"].student_account.student.full_name,
                r["invoice"].student_account.student.admission_number,
                r["invoice"].number,
                r["invoice"].currency.code,
                r["invoice"].due_date,
                r["days"],
                r["bucket"],
                r["outstanding"],
            ]
            for r in items
            if not start or r["invoice"].issue_date >= start
        ]
    if kind == "audit":
        qs = AuditEvent.objects.filter(tenant=member.tenant, action__startswith="finance.").order_by("created_at", "pk")
        if start:
            qs = qs.filter(created_at__date__gte=start)
        if end:
            qs = qs.filter(created_at__date__lte=end)
        if currency:
            raise ValidationError("Audit history has no universal currency field; clear the currency filter.")
        return ["Timestamp", "Action", "Actor", "Record"], [
            [e.created_at.isoformat(), e.action, str(e.actor_id or ""), e.object_id] for e in bounded(qs)
        ]
    if kind in ("ledger", "trial"):
        qs = JournalLine.objects.filter(journal__posted=True).select_related("journal__currency", "account")
        for value, lookup in [
            (currency, "journal__currency"),
            (start, "journal__date__gte"),
            (end, "journal__date__lte"),
        ]:
            if value:
                qs = qs.filter(**{lookup: value})
        lines = bounded(qs.order_by("journal__date", "journal__created_at", "pk"))
        if kind == "ledger":
            return ["Date", "Journal", "Source", "Currency", "Account", "Debit", "Credit"], [
                [
                    line.journal.date,
                    line.journal.reference,
                    line.journal.source,
                    line.journal.currency.code,
                    line.account.code,
                    line.debit,
                    line.credit,
                ]
                for line in lines
            ]
        totals = ledger_totals(qs, by_account=True)
        return ["Currency", "Account", "Name", "Debit movement", "Credit movement", "Net debit"], [
            [
                r["journal__currency__code"],
                r["account__code"],
                r["account__name"],
                r["debits"],
                r["credits"],
                r["debits"] - r["credits"],
            ]
            for r in totals
        ]
    qs = Payment.objects.select_related(
        "currency", "recorded_by__user", "student_account__student", "decision__journal__reversal"
    )
    for value, lookup in [(currency, "currency"), (start, "date__gte"), (end, "date__lte")]:
        if value:
            qs = qs.filter(**{lookup: value})
    payments = bounded(qs.order_by("date", "number"))
    if kind == "collections":
        return ["Date", "Payment", "Student", "Currency", "Amount", "Method", "Cashier", "Current status"], [
            [
                p.date,
                p.number,
                p.student_account.student.full_name,
                p.currency.code,
                p.amount,
                p.get_method_display(),
                str(p.recorded_by.user),
                payment_state(p, known_decision=getattr(p, "decision", False)),
            ]
            for p in payments
        ]
    totals = defaultdict(lambda: Decimal(0))
    for payment in payments:
        status = payment_state(payment, known_decision=getattr(payment, "decision", False))
        # Pending/rejected/reversed amounts remain explicitly separate from actual receipts.
        label = str(payment.recorded_by.user) if kind == "cashiers" else payment.get_method_display()
        totals[(payment.currency.code, label, status)] += payment.amount
    return ["Currency", "Cashier" if kind == "cashiers" else "Method", "Current status", "Amount"], [
        [*key, value] for key, value in sorted(totals.items())
    ]
