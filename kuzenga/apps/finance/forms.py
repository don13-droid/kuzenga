from django import forms

from apps.academics.models import AcademicYear, Term

from .models import Account, AccountingPeriod, Currency, FeeRule


class CurrencyForm(forms.ModelForm):
    class Meta:
        model = Currency
        fields = ["code", "name", "decimal_places"]


class FeeRuleForm(forms.ModelForm):
    class Meta:
        model = FeeRule
        fields = [
            "code",
            "name",
            "academic_year",
            "term",
            "grade",
            "class_group",
            "student_category",
            "boarding_status",
            "optional",
            "service_code",
            "currency",
            "amount",
            "income_account",
            "effective_from",
            "effective_to",
            "due_date",
        ]
        widgets = {
            key: forms.DateInput(attrs={"type": "date"}) for key in ["effective_from", "effective_to", "due_date"]
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.academics.models import AcademicYear, ClassGroup, Grade, Term

        for key, model in {
            "academic_year": AcademicYear,
            "term": Term,
            "grade": Grade,
            "class_group": ClassGroup,
            "currency": Currency,
            "income_account": Account,
        }.items():
            self.fields[key].queryset = model.objects.all()
        self.fields["income_account"].queryset = Account.objects.filter(kind="income", is_active=True)


class StatementForm(forms.Form):
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.none(), required=False)
    term = forms.ModelChoiceField(queryset=Term.objects.none(), required=False)
    currency = forms.ModelChoiceField(queryset=Currency.objects.none())
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.academics.models import AcademicYear, Term

        self.fields["academic_year"].queryset = AcademicYear.objects.all()
        self.fields["term"].queryset = Term.objects.all()
        self.fields["currency"].queryset = Currency.objects.all()

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["end"] < data["start"]:
            raise forms.ValidationError("End date cannot precede start date.")
        return data


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ["code", "name", "kind", "purpose", "description"]


class PeriodForm(forms.ModelForm):
    class Meta:
        model = AccountingPeriod
        fields = ["name", "starts_on", "ends_on"]
        widgets = {key: forms.DateInput(attrs={"type": "date"}) for key in ["starts_on", "ends_on"]}


class JournalForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].queryset = AccountingPeriod.objects.filter(closed=False)
        self.fields["currency"].queryset = Currency.objects.filter(is_active=True)

    reference = forms.CharField(max_length=64)
    idempotency_key = forms.CharField(max_length=100, widget=forms.HiddenInput)
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    period = forms.ModelChoiceField(queryset=AccountingPeriod.objects.filter(closed=False))
    currency = forms.ModelChoiceField(queryset=Currency.objects.filter(is_active=True))
    description = forms.CharField(max_length=500)
    source_reference = forms.CharField(max_length=100)


class JournalLineForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(is_active=True)

    account = forms.ModelChoiceField(queryset=Account.objects.filter(is_active=True))
    debit = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0, required=False)
    credit = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0, required=False)
    description = forms.CharField(max_length=255, required=False)


class ReportFilterForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["currency"].queryset = Currency.objects.all()

    currency = forms.ModelChoiceField(queryset=Currency.objects.all(), required=False)
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["end"] < data["start"]:
            raise forms.ValidationError("End date cannot precede start date.")
        return data
