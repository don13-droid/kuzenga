from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.tenancy.access import access_required

from . import operations as ops
from .models import CashSession, CashSubmission, FinanceImport, ReconciledEntry, ReconciliationMatch, StatementRow
from .operation_forms import CashCountForm, CashOpenForm, CSVImportForm, ImportReviewForm, MatchForm, ReviewForm
from .services import authorize


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def cashups(request):
    authorize(request.membership, "finance.view")
    qs = CashSession.objects.select_related("cashier__user", "currency", "submission__review")
    return render(request, "finance/cashups.html", {"page": Paginator(qs, 40).get_page(request.GET.get("page"))})


@access_required("finance", "finance.post")
@require_http_methods(["GET", "POST"])
def cash_open(request):
    authorize(request.membership, "finance.post")
    form = CashOpenForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            session = ops.open_cash(member=request.membership, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:cash-count", pk=session.pk)
    return render(request, "finance/form.html", {"form": form, "title": "Open cashier collection session"})


@access_required("finance", "finance.post")
@require_http_methods(["GET", "POST"])
def cash_count(request, pk):
    authorize(request.membership, "finance.post")
    session = get_object_or_404(CashSession, pk=pk)
    form = CashCountForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            ops.submit_cash(member=request.membership, session=session, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:cashups")
    return render(
        request,
        "finance/form.html",
        {"form": form, "title": f"Count cash — expected {session.currency.code} {ops.cash_expected(session)}"},
    )


@access_required("finance", "finance.approve")
@require_http_methods(["GET", "POST"])
def cash_review(request, pk):
    authorize(request.membership, "finance.approve")
    submission = get_object_or_404(CashSubmission, pk=pk)
    form = ReviewForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            ops.review_cash(
                member=request.membership,
                submission=submission,
                approved=form.cleaned_data["approved"] == "yes",
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:cashups")
    return render(
        request, "finance/form.html", {"form": form, "title": f"Review cash-up — difference {submission.difference}"}
    )


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def imports(request):
    authorize(request.membership, "finance.view")
    return render(
        request,
        "finance/imports.html",
        {
            "page": Paginator(FinanceImport.objects.select_related("requester__user"), 30).get_page(
                request.GET.get("page")
            )
        },
    )


@access_required("finance", "finance.post")
@require_http_methods(["GET", "POST"])
def import_new(request):
    authorize(request.membership, "finance.post")
    form = CSVImportForm(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        file = data.pop("file")
        try:
            source = file.read(1_000_001).decode("utf-8-sig")
            batch = ops.preview_import(member=request.membership, source=source, source_name=file.name, **data)
        except UnicodeError:
            form.add_error("file", "Use a valid UTF-8 CSV file.")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:import", pk=batch.pk)
    return render(request, "finance/import_upload.html", {"form": form})


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def import_detail(request, pk):
    authorize(request.membership, "finance.view")
    batch = get_object_or_404(FinanceImport, pk=pk)
    totals = defaultdict(lambda: {"debit": Decimal(0), "credit": Decimal(0), "net": Decimal(0)})
    for row in batch.rows:
        code = batch.currency.code if batch.kind == "statement" else row["code"]
        value = Decimal(row["amount"])
        totals[code]["debit" if value > 0 else "credit"] += abs(value)
        totals[code]["net"] += value
    preview_rows = batch.rows
    if batch.kind == "opening" and not hasattr(batch, "decision"):
        from .models import JournalLine

        current = defaultdict(lambda: Decimal(0))
        for sid, cid, debit, credit in (
            JournalLine.objects.filter(
                student_account__student_id__in=[r["student"] for r in batch.rows], journal__posted=True
            )
            .values_list("student_account__student_id", "journal__currency_id", "debit", "credit")
            .iterator()
        ):
            current[(str(sid), str(cid))] += debit - credit
        preview_rows = [
            {
                **row,
                "current": current[(row["student"], row["currency"])],
                "projected": current[(row["student"], row["currency"])] + Decimal(row["amount"]),
            }
            for row in batch.rows
        ]
    return render(
        request, "finance/import.html", {"batch": batch, "totals": dict(totals), "preview_rows": preview_rows}
    )


@access_required("finance", "finance.approve")
@require_http_methods(["GET", "POST"])
def import_review(request, pk):
    authorize(request.membership, "finance.approve")
    batch = get_object_or_404(FinanceImport, pk=pk)
    form = ImportReviewForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        data["approved"] = data["approved"] == "yes"
        try:
            ops.decide_import(member=request.membership, batch=batch, **data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:import", pk=pk)
    return render(request, "finance/form.html", {"form": form, "title": "Approve reviewed CSV source"})


@access_required("finance", "finance.view")
@require_http_methods(["GET"])
def reconciliation(request):
    authorize(request.membership, "finance.view")
    qs = StatementRow.objects.select_related("currency", "account").prefetch_related(
        Prefetch("reconciled_entries", queryset=ReconciledEntry.objects.filter(release__isnull=True).select_related("line__journal__reversal"), to_attr="current_matches")
    )
    matches = ReconciliationMatch.objects.select_related("row", "line__journal", "decision").order_by("-created_at")[
        :100
    ]
    return render(
        request,
        "finance/reconciliation.html",
        {"page": Paginator(qs, 40).get_page(request.GET.get("page")), "matches": matches},
    )


@access_required("finance", "finance.approve")
@require_http_methods(["GET", "POST"])
def match_release(request, pk):
    from django import forms
    authorize(request.membership, "finance.approve")
    entry = get_object_or_404(ReconciledEntry, pk=pk)
    class ReleaseForm(forms.Form):
        reason = forms.CharField(max_length=1000, widget=forms.Textarea)
    form = ReleaseForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            ops.release_match(member=request.membership, entry=entry, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:reconciliation")
    return render(request, "finance/form.html", {"form": form, "title": "Release incorrect reconciliation match"})


@access_required("finance", "finance.post")
@require_http_methods(["GET", "POST"])
def match_new(request):
    authorize(request.membership, "finance.post")
    form = MatchForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            ops.request_match(member=request.membership, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:reconciliation")
    return render(request, "finance/form.html", {"form": form, "title": "Propose statement-to-ledger match"})


@access_required("finance", "finance.approve")
@require_http_methods(["GET", "POST"])
def match_review(request, pk):
    authorize(request.membership, "finance.approve")
    match = get_object_or_404(ReconciliationMatch, pk=pk)
    form = ReviewForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            ops.decide_match(
                member=request.membership,
                match=match,
                approved=form.cleaned_data["approved"] == "yes",
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("finance:reconciliation")
    return render(
        request,
        "finance/form.html",
        {"form": form, "title": f"Review reconciliation: {match.row.reference} → {match.line.journal.reference}"},
    )
