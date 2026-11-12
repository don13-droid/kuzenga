import uuid

from django import forms
from django.utils import timezone

from .models import Account, AccountingPeriod, Currency, JournalLine, StatementRow


class ReviewForm(forms.Form):
    approved = forms.ChoiceField(choices=[("yes", "Approve"), ("no", "Reject")])
    reason = forms.CharField(max_length=1000, widget=forms.Textarea)


class CashOpenForm(forms.Form):
    on_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))
    currency = forms.ModelChoiceField(queryset=Currency.objects.none())
    account = forms.ModelChoiceField(queryset=Account.objects.none())
    opening_float = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["currency"].queryset = Currency.objects.filter(is_active=True)
        self.fields["account"].queryset = Account.objects.filter(kind="asset", purpose="cash", is_active=True)


class CashCountForm(forms.Form):
    actual = forms.DecimalField(max_digits=20, decimal_places=4, min_value=0, label="Actual cash counted")
    note = forms.CharField(max_length=1000, required=False, widget=forms.Textarea)


class CSVImportForm(forms.Form):
    kind = forms.ChoiceField(
        choices=[("statement", "Bank/mobile-money statement"), ("opening", "Student opening balances")]
    )
    file = forms.FileField(help_text="UTF-8 CSV, up to 1 MB and 500 rows. Source is retained privately for review.")
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(), required=False, label="Statement settlement account"
    )
    currency = forms.ModelChoiceField(queryset=Currency.objects.none(), required=False, label="Statement currency")
    receivable = forms.ModelChoiceField(
        queryset=Account.objects.none(), required=False, label="Opening receivable account"
    )
    offset = forms.ModelChoiceField(
        queryset=Account.objects.none(), required=False, label="Opening funds equity account"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(
            kind="asset", purpose__in=["bank", "mobile_clearing"], is_active=True
        )
        self.fields["currency"].queryset = Currency.objects.all()
        self.fields["receivable"].queryset = Account.objects.filter(purpose="receivable", is_active=True)
        self.fields["offset"].queryset = Account.objects.filter(kind="equity", purpose="opening", is_active=True)

    def clean_file(self):
        file = self.cleaned_data["file"]
        if file.size > 1_000_000 or not file.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a .csv file no larger than 1 MB.")
        return file


class ImportReviewForm(ReviewForm):
    period = forms.ModelChoiceField(queryset=AccountingPeriod.objects.none(), required=False)
    on_date = forms.DateField(
        initial=timezone.localdate, required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    acknowledged_existing = forms.BooleanField(
        required=False,
        label="I reviewed current balances and explicitly approve adding historical balances to existing activity",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].queryset = AccountingPeriod.objects.filter(closed=False)


class LedgerLineChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.journal.date} | {obj.journal.reference} | {obj.account.code} | {obj.journal.currency.code} {obj.debit - obj.credit}"


class MatchForm(forms.Form):
    row = forms.ModelChoiceField(queryset=StatementRow.objects.none())
    line = LedgerLineChoice(queryset=JournalLine.objects.none())
    reason = forms.CharField(
        max_length=1000, widget=forms.Textarea, label="Evidence and explanation of any date/reference differences"
    )
    idempotency_key = forms.CharField(max_length=100, widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import ReconciledEntry
        active = ReconciledEntry.objects.filter(release__isnull=True)
        self.fields["row"].queryset = StatementRow.objects.exclude(pk__in=active.values("row_id")).select_related("currency")
        self.fields["line"].queryset = JournalLine.objects.filter(
            account__purpose__in=["bank", "mobile_clearing"], journal__posted=True
        ).exclude(pk__in=active.values("line_id")).select_related("journal__currency", "account")
