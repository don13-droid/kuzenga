from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_uploaded_image


def tenant_logo_upload_to(_instance, filename):
    extension = Path(filename).suffix.lower()
    return f"tenant-logos/{uuid4().hex}{extension}"


class Tenant(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL = "trial", "Trial"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"

    class Currency(models.TextChoices):
        USD = "USD", "US Dollar"
        ZIG = "ZiG", "Zimbabwe Gold"

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    timezone = models.CharField(max_length=64, default="Africa/Harare")
    default_currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.USD
    )
    country = models.CharField(max_length=2, default="ZW")
    school_email = models.EmailField(blank=True)
    school_primary_phone = models.CharField(max_length=30, blank=True)
    school_alternative_phone = models.CharField(max_length=30, blank=True)
    physical_address = models.TextField(blank=True)
    postal_address = models.TextField(blank=True)
    website = models.URLField(blank=True)
    logo = models.ImageField(
        upload_to=tenant_logo_upload_to,
        blank=True,
        validators=[validate_uploaded_image],
    )

    def __str__(self):
        return self.name


def default_attendance_statuses():
    return [
        {"code": "present", "label": "Present"},
        {"code": "absent", "label": "Absent"},
        {"code": "late", "label": "Late"},
        {"code": "excused", "label": "Excused"},
    ]


class TenantConfiguration(TimeStampedModel):
    class MeasurementSystem(models.TextChoices):
        METRIC = "metric", "Metric"
        IMPERIAL = "imperial", "Imperial"

    class AttendanceReporting(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="configuration")
    date_format = models.CharField(max_length=20, default="d/m/Y")
    language = models.CharField(max_length=12, default="en")
    measurement_system = models.CharField(
        max_length=12, choices=MeasurementSystem.choices, default=MeasurementSystem.METRIC
    )
    attendance_statuses = models.JSONField(default=default_attendance_statuses)
    late_arrival_threshold_minutes = models.PositiveSmallIntegerField(default=15)
    attendance_reporting = models.CharField(
        max_length=12, choices=AttendanceReporting.choices, default=AttendanceReporting.DAILY
    )
    notify_by_email = models.BooleanField(default=True)
    notify_in_system = models.BooleanField(default=True)
    notify_announcements = models.BooleanField(default=True)
    notify_attendance = models.BooleanField(default=True)
    notify_academic_calendar = models.BooleanField(default=True)

    def __str__(self):
        return f"Configuration for {self.tenant}"


class Role(models.TextChoices):
    OWNER = "owner", "School owner / principal"
    ADMIN = "admin", "School administrator"
    BURSAR = "bursar", "Bursar / finance officer"
    TEACHER = "teacher", "Teacher"
    HOD = "hod", "Head of department"
    STAFF = "staff", "Other staff"
    GUARDIAN = "guardian", "Parent / guardian"
    STUDENT = "student", "Student"


class Membership(TimeStampedModel):
    """A user's role within one tenant. A user may belong to several tenants."""

    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant"], name="uniq_membership_user_tenant")
        ]

    def __str__(self):
        return f"{self.user} @ {self.tenant} ({self.role})"


# ---------------------------------------------------------------- subscriptions / entitlements
class Module(models.Model):
    """Catalogue entry for a paid/gated capability, e.g. 'attendance'."""

    code = models.SlugField(primary_key=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    depends_on = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="required_by"
    )

    def __str__(self):
        return self.name


class Plan(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    modules = models.ManyToManyField(Module, through="PlanModule", related_name="plans")

    def __str__(self):
        return self.name


class PlanModule(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE)
    module = models.ForeignKey(Module, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plan", "module"], name="uniq_plan_module")]


class Subscription(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        TRIAL = "trial", "Trial"
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due / grace"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    started_at = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["tenant", "-created_at"], name="subscription_tenant_time_idx")]

    def clean(self):
        super().clean()
        errors = {}
        if self.started_at and self.current_period_end and self.current_period_end <= self.started_at:
            errors["current_period_end"] = "Expiry must be after the start."
        if self.trial_ends_at:
            if not self.started_at or self.trial_ends_at <= self.started_at:
                errors["trial_ends_at"] = "Trial expiry must be after the start."
            elif self.current_period_end and self.trial_ends_at > self.current_period_end:
                errors["trial_ends_at"] = "Trial expiry cannot exceed the subscription expiry."
        if self.status in (self.Status.ACTIVE, self.Status.TRIAL):
            if not self.started_at:
                errors["started_at"] = "A start is required for access."
            if not self.current_period_end:
                errors["current_period_end"] = "An expiry is required for access."
        if self.status == self.Status.TRIAL and not self.trial_ends_at:
            errors["trial_ends_at"] = "A trial expiry is required."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.tenant} - {self.plan} ({self.status})"


class EntitlementQuerySet(models.QuerySet):
    def active(self):
        now = timezone.now()
        return self.filter(status=Entitlement.Status.ACTIVE, valid_from__lte=now).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gt=now)
        )


class Entitlement(TimeStampedModel):
    """What a tenant may actually use. Separate from the commercial Subscription record."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    class Source(models.TextChoices):
        PLAN = "plan", "Plan"
        ADDON = "addon", "Add-on"
        TRIAL = "trial", "Trial"
        PROMO = "promo", "Promotion"
        EXCEPTION = "exception", "Approved exception"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="entitlements")
    module = models.ForeignKey(Module, on_delete=models.PROTECT)
    subscription = models.ForeignKey(Subscription, null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.PLAN)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = EntitlementQuerySet.as_manager()

    def clean(self):
        super().clean()
        if self.subscription_id and self.subscription.tenant_id != self.tenant_id:
            raise ValidationError({"subscription": "The subscription must belong to this tenant."})
        if self.valid_until and self.valid_from and self.valid_until <= self.valid_from:
            raise ValidationError({"valid_until": "Expiry must be after the start."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tenant}: {self.module_id} ({self.status})"


class SubscriptionEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RuntimeError("Subscription events are immutable")

    def delete(self):
        raise RuntimeError("Subscription events are immutable")

    def bulk_update(self, objs, fields, batch_size=None):
        raise RuntimeError("Subscription events are immutable")


class SubscriptionEvent(models.Model):
    """Immutable subscription history."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="subscription_events")
    subscription = models.ForeignKey(Subscription, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=50)
    detail = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubscriptionEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Subscription events are immutable")
        if self.subscription_id and self.subscription.tenant_id != self.tenant_id:
            raise ValidationError("The subscription must belong to this tenant.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Subscription events are immutable")
