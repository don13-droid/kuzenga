from django import forms
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.academics.models import AcademicYear, Term
from apps.tenancy.access import access_required

from .dashboard import dashboard
from .forms import ReportFilterForm
from .services import authorize


class DashboardFilter(ReportFilterForm):
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.none(), required=False)
    term = forms.ModelChoiceField(queryset=Term.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["academic_year"].queryset = AcademicYear.objects.all()
        self.fields["term"].queryset = Term.objects.select_related("academic_year")


@access_required("finance", "finance.view")
@require_GET
def overview(request):
    authorize(request.membership, "finance.view")
    form = DashboardFilter(request.GET)
    data = {}
    if form.is_valid():
        try:
            data = dashboard(request.membership, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "finance/dashboard.html", {"form": form, **data})
