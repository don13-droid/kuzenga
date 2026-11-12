import csv
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.core import audit
from apps.tenancy.access import access_required

from .forms import ReportFilterForm
from .receipt_pdf import generate_document
from .reporting import KINDS, report_data
from .services import authorize


class FinanceReportForm(ReportFilterForm):
    kind = forms.ChoiceField(choices=KINDS)


def csv_cell(value):
    text = str(value)
    if isinstance(value, (Decimal, int)):
        return text
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def export_response(request, title, reference, headers, rows, lines=None):
    output = request.GET.get("format")
    if output == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        csv.writer(response).writerows([[csv_cell(c) for c in row] for row in [headers, *rows]])
    elif output == "pdf":
        if len(rows) > 500:
            raise ValidationError("Printable PDF exports support up to 500 rows; narrow the filters or use CSV.")
        body = [request.tenant.name, title, reference, "Values retain their stated currency.", ""]
        body += (
            lines
            if lines is not None
            else [
                text
                for index, row in enumerate(rows, 1)
                for text in [f"Record {index}", *[f"{heading}: {value}" for heading, value in zip(headers, row, strict=True)], ""]
            ]
        )
        response = HttpResponse(generate_document(request.tenant, reference, body), content_type="application/pdf")
    else:
        return None
    response["Content-Disposition"] = f'attachment; filename="{reference}.{output}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    audit.record("finance.report_exported", actor=request.user, report=title, rows=len(rows), format=output)
    return response


@access_required("finance", "finance.view")
@require_GET
def reports(request):
    authorize(request.membership, "finance.view")
    form = FinanceReportForm(request.GET if request.GET else None)
    headers, rows = [], []
    if form.is_bound and form.is_valid():
        try:
            headers, rows = report_data(request.membership, **form.cleaned_data)
            title = dict(KINDS)[form.cleaned_data["kind"]]
            filters = f"Dates {form.cleaned_data['start'] or 'all'} through {form.cleaned_data['end'] or 'all'}; currency {form.cleaned_data['currency'] or 'separate currencies'}"
            response = export_response(
                request, title + " - " + filters, "finance-" + form.cleaned_data["kind"], headers, rows
            )
            if response:
                return response
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request, "finance/reports.html", {"form": form, "headers": headers, "rows": rows[:100], "count": len(rows)}
    )
