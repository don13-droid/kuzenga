import uuid

from django import forms
from django.utils import timezone

from .models import Account, AccountingPeriod, Currency, FinanceRequest, Invoice, Payment, StudentAccount
from .workflow_forms import ReversalForm


class ControlRequestForm(forms.Form):
    kind = forms.ChoiceField(choices=FinanceRequest.KINDS)
    invoice = forms.ModelChoiceField(queryset=Invoice.objects.none(), required=False)
    payment = forms.ModelChoiceField(
        queryset=Payment.objects.none(), required=False, label="Original payment for an overpayment refund"
    )
    student_account = forms.ModelChoiceField(
        queryset=StudentAccount.objects.none(), required=False, help_text="For refunds without an invoice."
    )
    currency = forms.ModelChoiceField(
        queryset=Currency.objects.none(),
        required=False,
        help_text="For account-credit refunds only; invoice currency is otherwise retained.",
    )
    receivable_account = forms.ModelChoiceField(queryset=Account.objects.none(), required=False)
    counter_account = forms.ModelChoiceField(queryset=Account.objects.none())
    mode = forms.ChoiceField(choices=[("fixed", "Fixed amount"), ("percentage", "Percentage of original invoice")])
    value = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0)
    benefit_code = forms.CharField(max_length=60, label="Unique benefit / adjustment reference")
    effective_from = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    effective_to = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    eligibility = forms.CharField(max_length=1000, widget=forms.Textarea, label="Eligibility attestation")
    reason = forms.CharField(max_length=1000, widget=forms.Textarea)
    supporting_reference = forms.CharField(
        max_length=255,
        help_text="Private policy, scholarship, HR, sibling or evidence reference; no payment credentials.",
    )
    idempotency_key = forms.CharField(max_length=100, widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invoice"].queryset = Invoice.objects.all()
        self.fields["payment"].queryset = Payment.objects.all()
        self.fields["student_account"].queryset = StudentAccount.objects.select_related("student")
        self.fields["currency"].queryset = Currency.objects.filter(is_active=True)
        self.fields["receivable_account"].queryset = Account.objects.filter(purpose="receivable", is_active=True)
        self.fields["counter_account"].queryset = Account.objects.filter(is_active=True)


class DecisionForm(ReversalForm):
    approved = forms.ChoiceField(choices=[("yes", "Approve"), ("no", "Reject")])


class DisbursementForm(forms.Form):
    period = forms.ModelChoiceField(queryset=AccountingPeriod.objects.none())
    on_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))
    reference = forms.CharField(max_length=100)
    paid = forms.BooleanField(
        label="The actual refund was paid; I am recording its evidence, not initiating a transfer"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import AccountingPeriod

        self.fields["period"].queryset = AccountingPeriod.objects.filter(closed=False)
