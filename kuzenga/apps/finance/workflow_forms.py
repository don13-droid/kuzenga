import uuid

from django import forms
from django.utils import timezone

from apps.academics.models import ClassGroup
from apps.students.models import Student

from .forms import ReportFilterForm
from .models import Account, AccountingPeriod, Currency, FeeRule, Invoice, Payment, PaymentArrangement, StudentAccount


class BillingForm(forms.Form):
    fee = forms.ModelChoiceField(queryset=FeeRule.objects.none())
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), initial=timezone.localdate)
    period = forms.ModelChoiceField(queryset=AccountingPeriod.objects.none())
    receivable_account = forms.ModelChoiceField(queryset=Account.objects.none())
    students = forms.ModelMultipleChoiceField(
        queryset=Student.objects.none(),
        required=False,
        help_text="Select individual students, or leave blank to preview all eligible students in the selected scope.",
    )
    class_group = forms.ModelChoiceField(queryset=ClassGroup.objects.none(), required=False)
    boarding_status = forms.ChoiceField(
        choices=[("", "Not specified"), ("day", "Day"), ("boarding", "Boarding")], required=False
    )
    student_category = forms.CharField(
        max_length=60, required=False, help_text="For category-specific fees, explicitly identify the selected cohort."
    )
    opt_in = forms.BooleanField(required=False, label="The selected students opted into this optional fee/service")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, model in {"fee": FeeRule, "students": Student, "class_group": ClassGroup}.items():
            self.fields[key].queryset = model.objects.all()
        self.fields["period"].queryset = AccountingPeriod.objects.filter(closed=False)
        self.fields["receivable_account"].queryset = Account.objects.filter(purpose="receivable", is_active=True)


class PaymentForm(forms.Form):
    student = forms.ModelChoiceField(queryset=StudentAccount.objects.none(), label="Student account")
    currency = forms.ModelChoiceField(queryset=Currency.objects.none())
    value = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0, label="Amount")
    method = forms.ChoiceField(choices=Payment.METHODS)
    receiving_account = forms.ModelChoiceField(queryset=Account.objects.none())
    receivable_account = forms.ModelChoiceField(queryset=Account.objects.none())
    on_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))
    external_reference = forms.CharField(max_length=100, required=False)
    evidence_reference = forms.CharField(
        max_length=255,
        required=False,
        help_text="Private internal evidence reference; do not enter payment credentials.",
    )
    idempotency_key = forms.CharField(max_length=100, widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = StudentAccount.objects.select_related("student")
        self.fields["currency"].queryset = Currency.objects.filter(is_active=True)
        self.fields["receiving_account"].queryset = Account.objects.filter(kind="asset", is_active=True).exclude(
            purpose="receivable"
        )
        self.fields["receivable_account"].queryset = Account.objects.filter(purpose="receivable", is_active=True)


class ConfirmationForm(forms.Form):
    period = forms.ModelChoiceField(queryset=AccountingPeriod.objects.none())
    verified = forms.BooleanField(required=False, label="I independently verified this electronic payment")
    verification_reference = forms.CharField(max_length=255, required=False)
    auto_allocate = forms.BooleanField(required=False, initial=True, label="Allocate to oldest outstanding invoices")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].queryset = AccountingPeriod.objects.filter(closed=False)


class AllocationForm(forms.Form):
    on_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))
    invoice = forms.ModelChoiceField(queryset=Invoice.objects.none())
    value = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0, label="Amount to allocate")

    def __init__(self, *args, payment, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invoice"].queryset = Invoice.objects.filter(
            student_account=payment.student_account, currency=payment.currency
        )


class ReversalForm(forms.Form):
    period = forms.ModelChoiceField(queryset=AccountingPeriod.objects.none())
    on_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(max_length=500, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].queryset = AccountingPeriod.objects.filter(closed=False)


class RetractionForm(forms.Form):
    on_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(max_length=1000, widget=forms.Textarea)


class ArrangementForm(forms.Form):
    invoice = forms.ModelChoiceField(queryset=Invoice.objects.none())
    supersedes = forms.ModelChoiceField(
        queryset=PaymentArrangement.objects.none(), required=False, label="Previous arrangement being amended"
    )
    reason = forms.CharField(max_length=500, widget=forms.Textarea)
    idempotency_key = forms.CharField(max_length=100, widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invoice"].queryset = Invoice.objects.all()
        self.fields["supersedes"].queryset = PaymentArrangement.objects.filter(replacement__isnull=True)


class InstalmentForm(forms.Form):
    due = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    amount = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0)


class FollowUpForm(forms.Form):
    invoice = forms.ModelChoiceField(queryset=Invoice.objects.none())
    note = forms.CharField(max_length=2000, widget=forms.Textarea)
    promised_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    idempotency_key = forms.CharField(max_length=100, widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invoice"].queryset = Invoice.objects.all()


class DebtFilterForm(ReportFilterForm):
    as_of = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    minimum = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0, required=False)
    ageing_bands = forms.CharField(
        initial="30,60,90", required=False, help_text="Ascending overdue-day cutoffs, e.g. 30,60,90."
    )

    def clean_ageing_bands(self):
        try:
            result = tuple(int(x.strip()) for x in (self.cleaned_data["ageing_bands"] or "30,60,90").split(","))
        except ValueError as exc:
            raise forms.ValidationError("Use comma-separated whole day counts.") from exc
        if (
            not result
            or len(result) > 10
            or list(result) != sorted(set(result))
            or any(x < 1 or x > 3650 for x in result)
        ):
            raise forms.ValidationError("Use 1–10 ascending distinct cutoffs between 1 and 3650.")
        return result
