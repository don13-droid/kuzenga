"""Read-only statements and explicit, audited enrolment-account synchronisation."""

from decimal import Decimal

from django.db import transaction

from apps.core import audit
from apps.students.models import Student
from apps.tenancy.models import Tenant

from .models import JournalLine, StudentAccount
from .services import _scope, authorize


def profile_summary(student, member):
    from django.core.exceptions import PermissionDenied

    from .services import balances

    try:
        authorize(member, "finance.view")
    except PermissionDenied:
        return None
    account = StudentAccount.objects.filter(student=student).first()
    return {"account": account, "balances": balances(member, account)} if account else None


def account_for_enrolment(enrolment, actor):
    """Called by the authorised enrolment workflow; creates identity, never a charge."""
    from django.core.exceptions import PermissionDenied

    from apps.core.context import get_current_tenant
    from apps.tenancy.services import has_module

    tenant = get_current_tenant()
    if not tenant or tenant.pk != enrolment.tenant_id:
        raise PermissionDenied
    if not has_module(tenant, "finance"):
        return None
    account, created = StudentAccount.objects.get_or_create(student=enrolment.student)
    if created:
        audit.record(
            "finance.student_account_created",
            actor=actor,
            obj=account,
            source="student_enrolment",
            enrolment=enrolment.pk,
        )
    return account


@transaction.atomic
def sync_enrolled_accounts(member):
    member = authorize(member, "finance.configure")
    Tenant.objects.select_for_update().get(pk=member.tenant_id)
    students = Student.objects.filter(enrolments__isnull=False, financial_account__isnull=True).distinct()
    count = 0
    for student in students.iterator(chunk_size=250):
        account, created = StudentAccount.objects.get_or_create(student=student)
        if created:
            count += 1
            audit.record("finance.student_account_created", actor=member.user, obj=account)
    audit.record("finance.enrolled_accounts_synchronised", actor=member.user, created=count)
    return count


def statement(member, account, currency, start=None, end=None, academic_year=None, term=None):
    from django.core.exceptions import ValidationError

    authorize(member, "finance.view")
    from apps.academics.models import AcademicYear, Term

    year = _scope(AcademicYear, academic_year) if academic_year else None
    selected_term = _scope(Term, term) if term else None
    if year and selected_term and selected_term.academic_year_id != year.pk:
        raise ValidationError("Term must belong to the selected academic year.")
    for period in [year, selected_term]:
        if period:
            start = max(start, period.start_date) if start else period.start_date
            end = min(end, period.end_date) if end else period.end_date
    if start and end and start > end:
        raise ValidationError("The selected date ranges do not overlap.")
    account = _scope(StudentAccount, account)
    from .models import Currency

    currency = _scope(Currency, currency)
    qs = JournalLine.objects.filter(student_account=account, journal__posted=True, journal__currency=currency)
    opening = Decimal(0)
    if start:
        for debit, credit in qs.filter(journal__date__lt=start).values_list("debit", "credit").iterator():
            opening += debit - credit
        qs = qs.filter(journal__date__gte=start)
    if end:
        qs = qs.filter(journal__date__lte=end)
    running = opening
    rows = []
    for line in (
        qs.select_related("journal").order_by("journal__date", "journal__created_at", "pk").iterator(chunk_size=500)
    ):
        running += line.debit - line.credit
        rows.append({"line": line, "balance": running})
    return {
        "opening": opening,
        "closing": running,
        "outstanding": max(running, Decimal(0)),
        "credit": max(-running, Decimal(0)),
        "rows": rows,
    }
