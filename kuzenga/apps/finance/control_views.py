from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.tenancy.access import access_required

from . import controls
from .control_forms import ControlRequestForm, DecisionForm, DisbursementForm
from .models import FinanceDecision, FinanceRequest, InvoiceAdjustment
from .services import authorize
from .workflow_forms import ReversalForm


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def requests(request):
    authorize(request.membership, "finance.view")
    qs = FinanceRequest.objects.select_related("invoice", "currency", "student_account__student", "requester__user")
    return render(request, "finance/controls.html", {"page": Paginator(qs, 40).get_page(request.GET.get("page"))})


@access_required("finance", "finance.fees")
@require_http_methods(["GET", "POST"])
def request_create(request):
    authorize(request.membership, "finance.fees")
    form = ControlRequestForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            result = controls.request_control(member=request.membership, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:control", pk=result.pk)
    return render(request, "finance/form.html", {"form": form, "title": "Request concession or financial correction"})


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def detail(request, pk):
    authorize(request.membership, "finance.view")
    item = get_object_or_404(
        FinanceRequest.objects.select_related("currency", "student_account__student", "requester__user"), pk=pk
    )
    decision = (
        FinanceDecision.objects.filter(request=item)
        .select_related("actor__user", "journal__reversal", "disbursement__journal", "closure__journal")
        .first()
    )
    adjustment = InvoiceAdjustment.objects.filter(request=item).first()
    return render(request, "finance/control.html", {"item": item, "decision": decision, "adjustment": adjustment})


@access_required("finance", "finance.approve")
@require_http_methods(["GET", "POST"])
def decide(request, pk):
    authorize(request.membership, "finance.approve")
    item = get_object_or_404(FinanceRequest, pk=pk)
    form = DecisionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        data["approved"] = data["approved"] == "yes"
        try:
            controls.decide_control(member=request.membership, request=item, **data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:control", pk=pk)
    return render(request, "finance/form.html", {"form": form, "title": "Approve or reject " + item.number})


@access_required("finance", "finance.post")
@require_http_methods(["GET", "POST"])
def disburse(request, pk):
    authorize(request.membership, "finance.post")
    item = get_object_or_404(FinanceRequest, pk=pk)
    form = DisbursementForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        data.pop("paid")
        try:
            controls.disburse_refund(member=request.membership, request=item, **data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:control", pk=pk)
    return render(request, "finance/form.html", {"form": form, "title": "Record actual refund disbursement"})


@access_required("finance", "finance.approve")
@require_http_methods(["GET", "POST"])
def reverse(request, pk):
    authorize(request.membership, "finance.approve")
    item = get_object_or_404(FinanceRequest, pk=pk)
    form = ReversalForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            controls.reverse_control(member=request.membership, request=item, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:control", pk=pk)
    return render(request, "finance/form.html", {"form": form, "title": "Reverse posted adjustment " + item.number})
