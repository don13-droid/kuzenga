import uuid
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.core.models import AuditEvent
from apps.tenancy.access import access_required

from . import services
from .forms import AccountForm, CurrencyForm, JournalForm, JournalLineForm, PeriodForm, ReportFilterForm
from .models import Account, AccountingPeriod, Currency, Journal, JournalLine


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def overview(request):
    services.authorize(request.membership, "finance.view")
    totals = services.ledger_totals(JournalLine.objects.filter(journal__posted=True))
    return render(
        request,
        "finance/overview.html",
        {
            "totals": totals,
            "accounts": Account.objects.count(),
            "journals": Journal.objects.filter(posted=True).count(),
        },
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def chart(request):
    services.authorize(request.membership, "finance.view")
    return render(
        request, "finance/chart.html", {"page": Paginator(Account.objects.all(), 40).get_page(request.GET.get("page"))}
    )


@access_required("finance", "finance.configure")
@require_http_methods(["GET", "POST"])
def configuration(request, kind):
    services.authorize(request.membership, "finance.configure")
    choices = {
        "currencies": (Currency, CurrencyForm),
        "accounts": (Account, AccountForm),
        "periods": (AccountingPeriod, PeriodForm),
    }
    if kind not in choices:
        from django.http import Http404

        raise Http404
    model, form_type = choices[kind]
    form = form_type(request.POST or None, instance=model(tenant=request.tenant))
    if request.method == "POST" and form.is_valid():
        try:
            services.configure(model, form.cleaned_data, request.membership)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:chart")
    return render(request, "finance/form.html", {"form": form, "title": "Configure " + kind})


@access_required("finance", "finance.post")
@require_http_methods(["GET", "POST"])
def post(request):
    services.authorize(request.membership, "finance.post")
    form = JournalForm(request.POST or None, initial={"idempotency_key": str(uuid.uuid4())})
    LineSet = formset_factory(JournalLineForm, extra=4, max_num=100, validate_max=True, absolute_max=100)
    lines = LineSet(request.POST or None)
    if request.method == "POST":
        valid_form, valid_lines = form.is_valid(), lines.is_valid()
        if valid_form and valid_lines:
            try:
                journal = services.post_journal(
                    member=request.membership,
                    source="manual",
                    **form.cleaned_data,
                    lines=[
                        {**line, "debit": line.get("debit") or Decimal(0), "credit": line.get("credit") or Decimal(0)}
                        for line in lines.cleaned_data
                        if line
                    ],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Balanced journal posted. Posted entries cannot be edited.")
                return redirect("finance:journal", pk=journal.pk)
    return render(request, "finance/post.html", {"form": form, "lines": lines})


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def journal(request, pk):
    services.authorize(request.membership, "finance.view")
    entry = get_object_or_404(Journal.objects.select_related("currency", "created_by__user"), pk=pk, posted=True)
    return render(
        request,
        "finance/journal.html",
        {"entry": entry, "lines": entry.lines.select_related("account", "student_account__student")},
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def ledger(request):
    services.authorize(request.membership, "finance.view")
    form = ReportFilterForm(request.GET)
    qs = (
        JournalLine.objects.filter(journal__posted=True)
        .select_related("journal__currency", "account", "student_account__student")
        .order_by("journal__date", "journal__created_at", "pk")
    )
    if form.is_valid():
        for key, lookup in [
            ("currency", "journal__currency"),
            ("start", "journal__date__gte"),
            ("end", "journal__date__lte"),
        ]:
            if form.cleaned_data.get(key):
                qs = qs.filter(**{lookup: form.cleaned_data[key]})
    else:
        qs = qs.none()
    trial = services.ledger_totals(qs, by_account=True)
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "finance/ledger.html",
        {
            "form": form,
            "page": Paginator(qs, 50).get_page(request.GET.get("page")),
            "trial": trial,
            "filter_query": params.urlencode(),
        },
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def activity(request):
    services.authorize(request.membership, "finance.view")
    qs = AuditEvent.objects.filter(tenant=request.tenant, action__startswith="finance.").order_by("-created_at")
    return render(request, "finance/activity.html", {"page": Paginator(qs, 40).get_page(request.GET.get("page"))})


@access_required("finance", "finance.view")
@require_http_methods(["GET", "POST"])
def student_accounts(request):
    from .models import StudentAccount
    from .student_accounts import sync_enrolled_accounts

    services.authorize(request.membership, "finance.view")
    if request.method == "POST":
        count = sync_enrolled_accounts(request.membership)
        messages.success(request, f"Created {count} missing enrolled-student accounts. No charges were posted.")
        return redirect("finance:student-accounts")
    qs = StudentAccount.objects.select_related("student").order_by("student__last_name", "student__first_name")
    search = request.GET.get("q", "").strip()[:100]
    if search:
        from django.db.models import Q

        qs = qs.filter(
            Q(student__admission_number__icontains=search)
            | Q(student__last_name__icontains=search)
            | Q(student__first_name__icontains=search)
        )
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "finance/student_accounts.html",
        {
            "page": Paginator(qs, 40).get_page(request.GET.get("page")),
            "search": search,
            "filter_query": params.urlencode(),
        },
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def student_statement(request, pk):
    from .forms import StatementForm
    from .models import StudentAccount
    from .student_accounts import statement

    services.authorize(request.membership, "finance.view")
    account = get_object_or_404(StudentAccount.objects.select_related("student"), pk=pk)
    form = StatementForm(request.GET if request.GET else None)
    result = None
    if form.is_bound and form.is_valid():
        try:
            result = statement(request.membership, account, **form.cleaned_data)
            if request.GET.get("format") in ("csv", "pdf"):
                from .report_views import export_response
                if len(result["rows"]) > 5000:
                    raise ValidationError("Statement export exceeds 5,000 rows; narrow the date range.")
                currency = form.cleaned_data["currency"].code
                rows = [[r["line"].journal.date, r["line"].journal.reference, r["line"].journal.description,
                         currency, r["line"].debit, r["line"].credit, r["balance"]] for r in result["rows"]]
                title = f"Student statement: {account.student.full_name} / {account.student.admission_number} / {currency}; dates {form.cleaned_data['start'] or 'all'} through {form.cleaned_data['end'] or 'all'}"
                rows = [["Opening", "", "", currency, "", "", result["opening"]], *rows,
                        ["Closing", "", "", currency, "", "", result["closing"]]]
                return export_response(request, title, "statement-" + str(account.pk),
                                       ["Date", "Journal", "Description", "Currency", "Debit", "Credit", "Balance"], rows)
        except ValidationError as exc:
            form.add_error(None, exc)
    page = Paginator(result["rows"], 50).get_page(request.GET.get("page")) if result else None
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "finance/statement.html",
        {"account": account, "form": form, "statement": result, "page": page, "filter_query": params.urlencode()},
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def fees(request):
    from .models import FeeRule

    services.authorize(request.membership, "finance.view")
    qs = FeeRule.objects.select_related("currency", "academic_year", "term", "income_account")
    return render(request, "finance/fees.html", {"page": Paginator(qs, 40).get_page(request.GET.get("page"))})


@access_required("finance", "finance.fees")
@require_http_methods(["GET", "POST"])
def fee_create(request):
    from .forms import FeeRuleForm
    from .models import FeeRule

    services.authorize(request.membership, "finance.fees")
    form = FeeRuleForm(request.POST or None, instance=FeeRule(tenant=request.tenant))
    if request.method == "POST" and form.is_valid():
        try:
            services.configure(FeeRule, form.cleaned_data, request.membership)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:fees")
    return render(request, "finance/form.html", {"form": form, "title": "Create fee version"})
