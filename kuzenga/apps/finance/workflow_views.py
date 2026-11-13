from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.forms import formset_factory
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.core import audit
from apps.tenancy.access import access_required

from . import workflows as flow
from .models import DebtFollowUp, Invoice, Payment, PaymentArrangement, Receipt
from .services import authorize
from .workflow_forms import (
    AllocationForm,
    ArrangementForm,
    BillingForm,
    ConfirmationForm,
    DebtFilterForm,
    FollowUpForm,
    InstalmentForm,
    PaymentForm,
    ReversalForm,
)


def paginated(request, queryset):
    return Paginator(queryset, 40).get_page(request.GET.get("page"))


def filter_query(request):
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("account_page", None)
    return params.urlencode()


@access_required("finance", "finance.post")
@require_http_methods(["GET", "POST"])
def billing(request):
    authorize(request.membership, "finance.post")
    form = BillingForm(request.POST if request.method == "POST" else None)
    preview = token = None
    if request.method == "POST":
        try:
            if request.POST.get("action") == "post":
                data = signing.loads(request.POST.get("preview_token", ""), salt="finance-billing", max_age=900)
                if data.pop("member") != str(request.membership.pk) or data.pop("tenant") != str(request.tenant.pk):
                    raise ValidationError("Billing preview belongs to another school or user.")
                from datetime import date

                data["on_date"] = date.fromisoformat(data["on_date"])
                invoices = flow.bill_students(member=request.membership, **data)
                messages.success(
                    request, f"Billing completed: {len(invoices)} invoices, including any previously billed students."
                )
                return redirect("finance:invoices")
            if form.is_valid():
                cleaned = form.cleaned_data
                data = {
                    "fee": str(cleaned["fee"].pk),
                    "on_date": cleaned["date"].isoformat(),
                    "period": str(cleaned["period"].pk),
                    "receivable_account": str(cleaned["receivable_account"].pk),
                    "students": [str(s.pk) for s in cleaned["students"]] or None,
                    "class_group": str(cleaned["class_group"].pk) if cleaned["class_group"] else None,
                    "boarding_status": cleaned["boarding_status"],
                    "student_category": cleaned["student_category"],
                    "opt_in": cleaned["opt_in"],
                }
                preview = flow.billing_preview(
                    request.membership,
                    cleaned["fee"],
                    cleaned["date"],
                    students=data["students"],
                    class_group=data["class_group"],
                    boarding_status=data["boarding_status"],
                    student_category=data["student_category"],
                    opt_in=data["opt_in"],
                )
                # Freeze the exact reviewed cohort; do not silently add later enrolments.
                data["students"] = [str(s.pk) for s in preview["students"]]
                token = signing.dumps(
                    {**data, "member": str(request.membership.pk), "tenant": str(request.tenant.pk)},
                    salt="finance-billing",
                )
        except (ValidationError, signing.BadSignature) as exc:
            form.add_error(
                None,
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "The billing preview expired or was changed. Preview again.",
            )
    return render(request, "finance/billing.html", {"form": form, "preview": preview, "preview_token": token})


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def invoices(request):
    authorize(request.membership, "finance.view")
    page = paginated(request, Invoice.objects.select_related("student_account__student", "currency", "fee"))
    amounts = flow.invoice_balance_map(page)
    rows = [{"invoice": i, **amounts[i.pk]} for i in page]
    return render(request, "finance/invoices.html", {"page": page, "rows": rows})


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def invoice_detail(request, pk):
    authorize(request.membership, "finance.view")
    invoice = get_object_or_404(Invoice.objects.select_related("currency", "student_account__student", "fee"), pk=pk)
    return render(
        request,
        "finance/invoice.html",
        {
            "invoice": invoice,
            "paid": flow.invoice_paid(invoice),
            "outstanding": flow.invoice_outstanding(invoice),
            "allocations": invoice.allocations.select_related("decision__payment", "decision__journal"),
            "followups": invoice.follow_ups.select_related("actor__user"),
            "arrangements": [{"plan": p, "status": flow.arrangement_status(p)} for p in invoice.arrangements.all()],
        },
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def payments(request):
    authorize(request.membership, "finance.view")
    page = paginated(
        request,
        Payment.objects.select_related(
            "student_account__student", "currency", "recorded_by__user", "decision__journal__reversal"
        ),
    )
    return render(
        request,
        "finance/payments.html",
        {
            "page": page,
            "rows": [
                {"payment": p, "state": flow.payment_state(p, known_decision=getattr(p, "decision", False))}
                for p in page
            ],
        },
    )


@access_required("finance", "finance.post")
@require_http_methods(["GET", "POST"])
def payment_create(request):
    authorize(request.membership, "finance.post")
    form = PaymentForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            payment = flow.record_payment(member=request.membership, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:payment", pk=payment.pk)
    return render(request, "finance/form.html", {"form": form, "title": "Record pending payment"})


@access_required("finance", "finance.view")
@require_http_methods(["GET", "POST"])
def payment_detail(request, pk):
    authorize(request.membership, "finance.view")
    payment = get_object_or_404(Payment.objects.select_related("student_account__student", "currency"), pk=pk)
    action = request.POST.get("action")
    confirm = ConfirmationForm(request.POST if request.method == "POST" and action == "confirm" else None)
    allocate = AllocationForm(
        request.POST if request.method == "POST" and action == "allocate" else None, payment=payment
    )
    if request.method == "POST":
        try:
            if action == "confirm" and confirm.is_valid():
                receipt = flow.confirm_payment(member=request.membership, payment=payment, **confirm.cleaned_data)
                return redirect("finance:receipt", pk=receipt.pk)
            if action == "allocate" and allocate.is_valid():
                flow.allocate_payment(member=request.membership, payment=payment, **allocate.cleaned_data)
                return redirect("finance:payment", pk=pk)
            if action == "reject":
                flow.reject_payment(member=request.membership, payment=payment, reason=request.POST.get("reason", ""))
                return redirect("finance:payment", pk=pk)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    from .models import PaymentDecision

    decision = PaymentDecision.objects.filter(payment=payment).select_related("receipt").first()
    used = sum(flow.active_allocations().filter(decision__payment=payment).values_list("amount", flat=True), Decimal(0))
    from .controls import payment_refund_reservations
    return render(
        request,
        "finance/payment.html",
        {
            "payment": payment,
            "state": flow.payment_state(payment),
            "confirm_form": confirm,
            "allocation_form": allocate,
            "decision": decision,
            "available": payment.amount - used - payment_refund_reservations(payment) if flow.payment_state(payment) == "confirmed" else Decimal(0),
            "allocations": payment.decision.allocations.select_related("invoice", "retraction__actor__user") if decision else [],
        },
    )


@access_required("finance", "finance.approve")
@require_http_methods(["GET", "POST"])
def allocation_retract(request, pk):
    from .models import PaymentAllocation
    from .workflow_forms import RetractionForm

    authorize(request.membership, "finance.approve")
    allocation = get_object_or_404(PaymentAllocation.objects.select_related("decision__payment", "invoice"), pk=pk)
    form = RetractionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            flow.retract_allocation(member=request.membership, allocation=allocation, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:payment", pk=allocation.decision.payment_id)
    return render(request, "finance/form.html", {"form": form, "title": "Retract allocation to " + allocation.invoice.number})


@access_required("finance", "finance.approve")
@require_http_methods(["GET", "POST"])
def payment_reverse(request, pk):
    authorize(request.membership, "finance.approve")
    payment = get_object_or_404(Payment, pk=pk)
    form = ReversalForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            flow.reverse_payment(member=request.membership, payment=payment, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:payment", pk=pk)
    return render(request, "finance/form.html", {"form": form, "title": "Reverse payment " + payment.number})


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def receipts(request):
    authorize(request.membership, "finance.view")
    qs = Receipt.objects.select_related("decision__payment")
    search = request.GET.get("q", "").strip()[:100]
    if search:
        from django.db.models import Q

        qs = qs.filter(
            Q(number__icontains=search)
            | Q(decision__payment__number__icontains=search)
            | Q(decision__payment__external_reference__icontains=search)
        )
    return render(
        request,
        "finance/receipts.html",
        {"page": paginated(request, qs), "search": search, "filter_query": filter_query(request)},
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def receipt_detail(request, pk):
    authorize(request.membership, "finance.view")
    receipt = get_object_or_404(Receipt.objects.select_related("decision__payment"), pk=pk)
    return render(
        request,
        "finance/receipt.html",
        {"receipt": receipt, "void": flow.payment_state(receipt.decision.payment) == "reversed"},
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def receipt_pdf(request, pk):
    authorize(request.membership, "finance.view")
    from .receipt_pdf import generate_receipt

    receipt = get_object_or_404(Receipt.objects.select_related("decision__payment"), pk=pk)
    # Issued receipt remains immutable. Every downloaded copy is clearly labelled COPY.
    void = flow.payment_state(receipt.decision.payment) == "reversed"
    response = HttpResponse(generate_receipt(request.tenant, receipt, void), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{receipt.number}.pdf"'
    response["Cache-Control"] = "private, no-store"
    audit.record("finance.receipt_reprinted", actor=request.user, obj=receipt, reference=receipt.number, void=void)
    return response


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def debt(request):
    authorize(request.membership, "finance.view")
    form = DebtFilterForm(request.GET)
    rows = []
    ledger_balances = []
    if form.is_valid():
        data = form.cleaned_data
        ledger_balances = flow.student_debt_balances(request.membership, data["currency"], data["as_of"])
        rows = flow.debt_rows(
            request.membership,
            currency=data["currency"],
            on_date=data["as_of"],
            bands=data["ageing_bands"],
            minimum=data["minimum"] or Decimal(0),
        )
        rows = [
            r
            for r in rows
            if (not data["start"] or r["invoice"].issue_date >= data["start"])
            and (not data["end"] or r["invoice"].issue_date <= data["end"])
        ]
    totals = defaultdict(lambda: Decimal(0))
    for row in rows:
        totals[row["invoice"].currency.code] += row["outstanding"]
    return render(
        request,
        "finance/debt.html",
        {
            "form": form,
            "page": paginated(request, rows),
            "totals": dict(totals),
            "account_page": Paginator(ledger_balances, 40).get_page(request.GET.get("account_page")),
            "filter_query": filter_query(request),
        },
    )


@access_required("finance", "finance.fees")
@require_http_methods(["GET", "POST"])
def arrangement(request):
    authorize(request.membership, "finance.fees")
    form = ArrangementForm(request.POST if request.method == "POST" else None)
    Set = formset_factory(InstalmentForm, extra=6, max_num=24, validate_max=True, absolute_max=24)
    instalments = Set(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        valid, valid_instalments = form.is_valid(), instalments.is_valid()
        if valid and valid_instalments:
            try:
                plan = flow.arrange_payment(
                    member=request.membership, schedule=[i for i in instalments.cleaned_data if i], **form.cleaned_data
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                return redirect("finance:invoice", pk=plan.invoice_id)
    return render(request, "finance/arrangement.html", {"form": form, "instalments": instalments})


@access_required("finance", "finance.fees")
@require_http_methods(["GET", "POST"])
def followup(request):
    authorize(request.membership, "finance.fees")
    form = FollowUpForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            note = flow.follow_up(member=request.membership, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:invoice", pk=note.invoice_id)
    return render(request, "finance/form.html", {"form": form, "title": "Record debt collection follow-up"})


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def collections(request):
    authorize(request.membership, "finance.view")
    form = DebtFilterForm(request.GET)
    totals = {}
    qs = Payment.objects.select_related("currency", "recorded_by__user", "decision__journal__reversal")
    if form.is_valid():
        data = form.cleaned_data
        for field, lookup in [("currency", "currency"), ("start", "date__gte"), ("end", "date__lte")]:
            if data.get(field):
                qs = qs.filter(**{lookup: data[field]})
        for payment in qs:
            state = flow.payment_state(payment, known_decision=getattr(payment, "decision", False))
            key = (payment.currency.code, payment.date.strftime("%Y-%m"), payment.get_method_display(), state)
            totals[key] = totals.get(key, Decimal(0)) + payment.amount
    return render(
        request,
        "finance/collections.html",
        {
            "form": form,
            "rows": sorted(totals.items()),
            "plans": [
                {"plan": p, "status": flow.arrangement_status(p)}
                for p in PaymentArrangement.objects.filter(replacement__isnull=True).select_related("invoice")[:100]
            ],
            "followups": DebtFollowUp.objects.select_related("invoice", "actor__user")[:100],
        },
    )
