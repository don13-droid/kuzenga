"""Finance persistence. Posted journals/lines are also protected by database triggers."""

from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.context import get_current_tenant
from apps.core.models import TenantManager, TenantScopedModel

_ledger_write = ContextVar("finance_ledger_write", default=False)


class FinanceModel(TenantScopedModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            self.tenant = get_current_tenant()
        self._check_related_tenants()
        self.full_clean()
        return super().save(*args, **kwargs)


class Currency(FinanceModel):
    code = models.CharField(max_length=8)
    name = models.CharField(max_length=60)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="finance_currency_code"),
            models.CheckConstraint(condition=models.Q(decimal_places__lte=4), name="finance_currency_precision"),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        self.code = self.code.strip().upper()
        if not self.code:
            raise ValidationError("A nonempty code is required.")
        if not self.code.isascii() or not self.code.isalnum():
            raise ValidationError("Currency code must contain ASCII letters/numbers.")
        if not self._state.adding and Journal.objects.filter(currency=self).exists():
            original = Currency.objects.get(pk=self.pk)
            if (original.code, original.decimal_places) != (self.code, self.decimal_places):
                raise ValidationError("Posted currency code and precision cannot change.")


class Account(FinanceModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    kind = models.CharField(
        max_length=12, choices=[(x, x.title()) for x in ["asset", "liability", "equity", "income", "expense"]]
    )
    purpose = models.CharField(
        max_length=24,
        choices=[
            (x, x.replace("_", " ").title())
            for x in [
                "cash",
                "bank",
                "mobile_clearing",
                "receivable",
                "tuition",
                "boarding",
                "transport",
                "other_income",
                "concession",
                "refund",
                "unallocated",
                "opening",
                "bad_debt",
                "other",
            ]
        ],
        default="other",
    )
    description = models.TextField(blank=True, max_length=1000)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="finance_account_code")]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def clean(self):
        if self.purpose == "receivable" and self.kind != "asset":
            raise ValidationError("Student receivables must use an asset account.")
        if not self._state.adding and JournalLine.objects.filter(account=self).exists():
            original = Account.objects.get(pk=self.pk)
            if (original.code, original.kind, original.purpose) != (self.code, self.kind, self.purpose):
                raise ValidationError("An account used by the ledger cannot change its code, type or purpose.")


class AccountingPeriod(FinanceModel):
    name = models.CharField(max_length=100)
    starts_on = models.DateField()
    ends_on = models.DateField()
    closed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-starts_on"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="finance_period_name"),
            models.CheckConstraint(condition=models.Q(ends_on__gte=models.F("starts_on")), name="finance_period_dates"),
        ]

    def clean(self):
        if (
            self.starts_on
            and self.ends_on
            and AccountingPeriod.objects.filter(starts_on__lte=self.ends_on, ends_on__gte=self.starts_on)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError("Accounting periods must not overlap.")

    def __str__(self):
        return self.name


class StudentAccount(FinanceModel):
    student = models.OneToOneField("students.Student", on_delete=models.PROTECT, related_name="financial_account")

    def __str__(self):
        return str(self.student)


class FeeQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Fee versions cannot be overwritten.")

    def delete(self):
        raise ValidationError("Preserve historical fee versions.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Fee versions cannot be overwritten.")


class FeeRule(FinanceModel):
    objects = TenantManager.from_queryset(FeeQuerySet)()
    unscoped = FeeQuerySet.as_manager()
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    term = models.ForeignKey("academics.Term", null=True, blank=True, on_delete=models.PROTECT)
    grade = models.ForeignKey("academics.Grade", null=True, blank=True, on_delete=models.PROTECT)
    class_group = models.ForeignKey("academics.ClassGroup", null=True, blank=True, on_delete=models.PROTECT)
    student_category = models.CharField(max_length=60, blank=True)
    boarding_status = models.CharField(
        max_length=10, choices=[("", "Any"), ("day", "Day"), ("boarding", "Boarding")], blank=True
    )
    optional = models.BooleanField(default=False)
    service_code = models.CharField(max_length=40, blank=True)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    income_account = models.ForeignKey(Account, on_delete=models.PROTECT)
    effective_from = models.DateField()
    effective_to = models.DateField()
    due_date = models.DateField()

    class Meta:
        ordering = ["code", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "tenant",
                    "code",
                    "effective_from",
                    "academic_year",
                    "currency",
                    "term",
                    "grade",
                    "class_group",
                    "boarding_status",
                    "student_category",
                ],
                name="finance_fee_version",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="finance_fee_positive"),
            models.CheckConstraint(
                condition=models.Q(effective_to__gte=models.F("effective_from")), name="finance_fee_dates"
            ),
        ]

    def clean(self):
        from .services import amount

        self.code = self.code.strip().upper()
        if not self.code:
            raise ValidationError("A nonempty fee code is required.")
        if self.currency_id and not self.currency.is_active:
            raise ValidationError("Choose an active currency.")
        if self.currency_id and self.amount is not None:
            amount(self.amount, self.currency)
        if self.income_account_id and (self.income_account.kind != "income" or not self.income_account.is_active):
            raise ValidationError("Choose an active income account.")
        if self.term_id and self.term.academic_year_id != self.academic_year_id:
            raise ValidationError("Term must belong to the selected year.")
        if self.class_group_id and (
            self.class_group.academic_year_id != self.academic_year_id
            or (self.grade_id and self.class_group.grade_id != self.grade_id)
        ):
            raise ValidationError("Class, grade and academic year must agree.")
        if self.academic_year_id and self.effective_from and self.effective_to:
            if self.effective_from < self.academic_year.start_date or self.effective_to > self.academic_year.end_date:
                raise ValidationError("Fee effective dates must fall within the academic year.")
            peers = FeeRule.objects.filter(
                code=self.code,
                academic_year_id=self.academic_year_id,
                currency_id=self.currency_id,
                effective_from__lte=self.effective_to,
                effective_to__gte=self.effective_from,
            ).exclude(pk=self.pk)
            for peer in peers.select_related("class_group"):
                if self.term_id and peer.term_id and self.term_id != peer.term_id:
                    continue
                if self.boarding_status and peer.boarding_status and self.boarding_status != peer.boarding_status:
                    continue
                if self.student_category and peer.student_category and self.student_category != peer.student_category:
                    continue
                if self.class_group_id and peer.class_group_id and self.class_group_id != peer.class_group_id:
                    continue
                self_grade = self.grade_id or (self.class_group.grade_id if self.class_group_id else None)
                peer_grade = peer.grade_id or (peer.class_group.grade_id if peer.class_group_id else None)
                if self_grade and peer_grade and self_grade != peer_grade:
                    continue
                raise ValidationError("This fee overlaps an existing rule for the same charge and students.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Fee versions cannot be overwritten. Create a nonoverlapping replacement.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Preserve historical fee versions.")

    def __str__(self):
        return f"{self.code} — {self.name} ({self.currency.code} {self.amount})"


class LedgerQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use finance posting/reversal services.")

    def delete(self):
        raise ValidationError("Ledger history cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Ledger history cannot be rewritten.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Use finance posting services.")


class LedgerModel(FinanceModel):
    objects = TenantManager.from_queryset(LedgerQuerySet)()
    unscoped = LedgerQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _ledger_write.get() or not self._state.adding:
            raise ValidationError("Use finance posting services; ledger rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Ledger history cannot be deleted.")


class Journal(LedgerModel):
    reference = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)
    date = models.DateField(db_index=True)
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    description = models.CharField(max_length=500)
    source = models.CharField(max_length=40)
    source_reference = models.CharField(max_length=100)
    posted = models.BooleanField(default=False, editable=False)
    created_by = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    reversal_of = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal")
    exchange_rate = models.DecimalField(max_digits=24, decimal_places=10, null=True, blank=True)
    rate_effective_date = models.DateField(null=True, blank=True)
    rate_reference = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["date", "created_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reference"], name="finance_journal_reference"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="finance_journal_idempotency"),
            models.CheckConstraint(
                condition=models.Q(exchange_rate__isnull=True) | models.Q(exchange_rate__gt=0),
                name="finance_positive_rate",
            ),
        ]


class JournalLine(LedgerModel):
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    student_account = models.ForeignKey(
        StudentAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="journal_lines"
    )
    debit = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    credit = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(debit__gt=0, credit=0) | models.Q(credit__gt=0, debit=0),
                name="finance_line_single_side",
            )
        ]
        indexes = [models.Index(fields=["tenant", "student_account", "journal"], name="finance_student_ledger_idx")]

    def clean(self):
        if self.account_id and (self.account.purpose == "receivable") != bool(self.student_account_id):
            raise ValidationError("A student dimension is required only on student receivable lines.")


class DocumentSequence(FinanceModel):
    kind = models.CharField(max_length=12)
    last_number = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "kind"], name="finance_document_sequence")]


class Invoice(LedgerModel):
    number = models.CharField(max_length=40)
    student_account = models.ForeignKey(StudentAccount, on_delete=models.PROTECT, related_name="invoices")
    fee = models.ForeignKey(FeeRule, on_delete=models.PROTECT)
    journal = models.OneToOneField(Journal, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    issue_date = models.DateField()
    due_date = models.DateField(db_index=True)
    snapshot = models.JSONField()

    class Meta:
        ordering = ["-issue_date", "number"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="finance_invoice_number"),
            models.UniqueConstraint(fields=["tenant", "student_account", "fee"], name="finance_invoice_fee_once"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="finance_invoice_positive"),
        ]

    def __str__(self):
        return self.number


class Payment(LedgerModel):
    METHODS = [
        (code, label)
        for code, label in [
            ("cash", "Cash"),
            ("bank_transfer", "Bank transfer"),
            ("bank_deposit", "Bank deposit"),
            ("ecocash", "EcoCash"),
            ("onemoney", "OneMoney"),
            ("innbucks", "InnBucks"),
            ("pos", "Card / POS"),
            ("other", "Other recorded payment"),
        ]
    ]
    number = models.CharField(max_length=40)
    idempotency_key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)
    student_account = models.ForeignKey(StudentAccount, on_delete=models.PROTECT, related_name="payments")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    method = models.CharField(max_length=20, choices=METHODS)
    external_reference = models.CharField(max_length=100, blank=True)
    evidence_reference = models.CharField(max_length=255, blank=True)
    receiving_account = models.ForeignKey(Account, on_delete=models.PROTECT)
    receivable_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    date = models.DateField(db_index=True)
    recorded_by = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="finance_payment_number"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="finance_payment_idempotency"),
            models.UniqueConstraint(
                fields=["tenant", "method", "external_reference"],
                condition=~models.Q(external_reference=""),
                name="finance_payment_external_once",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="finance_payment_positive"),
        ]

    def __str__(self):
        return self.number


class PaymentDecision(LedgerModel):
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="decision")
    journal = models.OneToOneField(Journal, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    verification_reference = models.CharField(max_length=255, blank=True)


class PaymentAllocation(LedgerModel):
    decision = models.ForeignKey(PaymentDecision, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    effective_date = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "decision", "invoice"], name="finance_allocation_once"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="finance_allocation_positive"),
        ]


class Receipt(LedgerModel):
    number = models.CharField(max_length=40)
    decision = models.OneToOneField(PaymentDecision, on_delete=models.PROTECT, related_name="receipt")
    snapshot = models.JSONField()

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "number"], name="finance_receipt_number")]

    def __str__(self):
        return self.number


class PaymentArrangement(LedgerModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="arrangements")
    idempotency_key = models.CharField(max_length=100)
    schedule = models.JSONField()
    baseline_paid = models.DecimalField(max_digits=20, decimal_places=4)
    reason = models.CharField(max_length=500)
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    supersedes = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="replacement"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="finance_arrangement_idempotency")
        ]


class DebtFollowUp(LedgerModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="follow_ups")
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    note = models.CharField(max_length=2000)
    promised_date = models.DateField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=100)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="finance_followup_idempotency")
        ]


class FinanceRequest(LedgerModel):
    KINDS = [
        (x, x.replace("_", " ").title())
        for x in [
            "discount",
            "scholarship",
            "bursary",
            "sibling",
            "staff_child",
            "waiver",
            "credit",
            "debit",
            "write_off",
            "refund",
        ]
    ]
    number = models.CharField(max_length=40)
    kind = models.CharField(max_length=20, choices=KINDS)
    invoice = models.ForeignKey(Invoice, null=True, blank=True, on_delete=models.PROTECT)
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.PROTECT)
    student_account = models.ForeignKey(StudentAccount, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    receivable_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    counter_account = models.ForeignKey(Account, on_delete=models.PROTECT)
    mode = models.CharField(
        max_length=12, choices=[("fixed", "Fixed amount"), ("percentage", "Percentage of original invoice")]
    )
    value = models.DecimalField(max_digits=20, decimal_places=4)
    benefit_code = models.CharField(max_length=60)
    effective_from = models.DateField()
    effective_to = models.DateField()
    eligibility = models.CharField(max_length=1000)
    reason = models.CharField(max_length=1000)
    supporting_reference = models.CharField(max_length=255)
    requester = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="finance_request_number"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="finance_request_key"),
            models.UniqueConstraint(fields=["tenant", "invoice", "benefit_code"], name="finance_invoice_benefit_once"),
            models.CheckConstraint(condition=models.Q(value__gt=0), name="finance_request_positive"),
            models.CheckConstraint(
                condition=models.Q(effective_to__gte=models.F("effective_from")), name="finance_request_dates"
            ),
        ]

    def __str__(self):
        return f"{self.number} — {self.get_kind_display()}"


class FinanceDecision(LedgerModel):
    request = models.OneToOneField(FinanceRequest, on_delete=models.PROTECT, related_name="decision")
    approved = models.BooleanField()
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    journal = models.OneToOneField(Journal, null=True, blank=True, on_delete=models.PROTECT)


class InvoiceAdjustment(LedgerModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="adjustments")
    request = models.OneToOneField(FinanceRequest, on_delete=models.PROTECT)
    journal = models.OneToOneField(Journal, on_delete=models.PROTECT)
    direction = models.CharField(max_length=6, choices=[("credit", "Credit reduction"), ("debit", "Debit charge")])
    amount = models.DecimalField(max_digits=20, decimal_places=4)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="finance_adjustment_positive")]


class RefundDisbursement(LedgerModel):
    decision = models.OneToOneField(FinanceDecision, on_delete=models.PROTECT, related_name="disbursement")
    journal = models.OneToOneField(Journal, on_delete=models.PROTECT)
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    reference = models.CharField(max_length=100)
    date = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "reference"], name="finance_refund_disbursement_ref")]


class CashSession(LedgerModel):
    cashier = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    date = models.DateField()
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    opening_float = models.DecimalField(max_digits=20, decimal_places=4)

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "cashier", "date", "currency", "account"], name="finance_cash_session_once"
            )
        ]

    def __str__(self):
        return f"{self.date} — {self.currency.code} — {self.cashier.user}"


class CashSubmission(LedgerModel):
    session = models.OneToOneField(CashSession, on_delete=models.PROTECT, related_name="submission")
    expected = models.DecimalField(max_digits=20, decimal_places=4)
    actual = models.DecimalField(max_digits=20, decimal_places=4)
    difference = models.DecimalField(max_digits=20, decimal_places=4)
    note = models.CharField(max_length=1000)


class CashReview(LedgerModel):
    submission = models.OneToOneField(CashSubmission, on_delete=models.PROTECT, related_name="review")
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    approved = models.BooleanField()
    reason = models.CharField(max_length=1000)


class FinanceImport(LedgerModel):
    kind = models.CharField(
        max_length=12, choices=[("statement", "Bank/mobile statement"), ("opening", "Student opening balances")]
    )
    source_name = models.CharField(max_length=100)
    source = models.TextField()
    digest = models.CharField(max_length=64)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    currency = models.ForeignKey(Currency, null=True, blank=True, on_delete=models.PROTECT)
    receivable = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    offset = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    rows = models.JSONField(blank=True)
    errors = models.JSONField(blank=True)
    requester = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "digest"], name="finance_import_digest_once")]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.source_name}"


class ImportDecision(LedgerModel):
    batch = models.OneToOneField(FinanceImport, on_delete=models.PROTECT, related_name="decision")
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    approved = models.BooleanField()
    reason = models.CharField(max_length=1000)
    acknowledged_existing = models.BooleanField(default=False)


class StatementRow(LedgerModel):
    batch = models.ForeignKey(FinanceImport, on_delete=models.PROTECT, related_name="statement_rows")
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    date = models.DateField()
    reference = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    fingerprint = models.CharField(max_length=64)

    class Meta:
        ordering = ["-date", "reference"]
        constraints = [models.UniqueConstraint(fields=["tenant", "fingerprint"], name="finance_statement_row_once")]

    def __str__(self):
        return f"{self.date} {self.reference} {self.currency.code} {self.amount}"


class OpeningEntry(LedgerModel):
    batch = models.ForeignKey(FinanceImport, on_delete=models.PROTECT, related_name="opening_entries")
    student_account = models.ForeignKey(StudentAccount, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    reference = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    journal = models.OneToOneField(Journal, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "student_account", "currency"], name="finance_opening_student_currency_once"
            )
        ]


class ReconciliationMatch(LedgerModel):
    row = models.ForeignKey(StatementRow, on_delete=models.PROTECT)
    line = models.ForeignKey(JournalLine, on_delete=models.PROTECT)
    requester = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
    idempotency_key = models.CharField(max_length=100)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="finance_match_request_key")]

    def __str__(self):
        return f"{self.row.reference} → {self.line.journal.reference}"


class MatchDecision(LedgerModel):
    match = models.OneToOneField(ReconciliationMatch, on_delete=models.PROTECT, related_name="decision")
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    approved = models.BooleanField()
    reason = models.CharField(max_length=1000)


class ReconciledEntry(LedgerModel):
    decision = models.OneToOneField(MatchDecision, on_delete=models.PROTECT)
    row = models.ForeignKey(StatementRow, on_delete=models.PROTECT, related_name="reconciled_entries")
    line = models.ForeignKey(JournalLine, on_delete=models.PROTECT, related_name="reconciled_entries")


class RefundClosure(LedgerModel):
    decision = models.OneToOneField(FinanceDecision, on_delete=models.PROTECT, related_name="closure")
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
    journal = models.OneToOneField(Journal, null=True, blank=True, on_delete=models.PROTECT)


class AllocationRetraction(LedgerModel):
    allocation = models.OneToOneField(PaymentAllocation, on_delete=models.PROTECT, related_name="retraction")
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    date = models.DateField()
    reason = models.CharField(max_length=1000)


class ReconciliationRelease(LedgerModel):
    entry = models.OneToOneField(ReconciledEntry, on_delete=models.PROTECT, related_name="release")
    actor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
