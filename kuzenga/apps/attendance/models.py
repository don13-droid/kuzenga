from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.academics.models import ClassGroup
from apps.core.models import TenantScopedModel
from apps.students.models import Student


class AttendanceSession(TenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        SUBMITTED = "submitted", "Submitted"

    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.PROTECT, related_name="attendance_sessions"
    )
    term = models.ForeignKey("academics.Term", null=True, blank=True, on_delete=models.PROTECT)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "class_group", "date"], name="uniq_register_per_class_day"
            )
        ]


class AttendanceRecord(TenantScopedModel):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        LATE = "late", "Late"
        EXCUSED = "excused", "Excused"

    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name="records")
    student = models.ForeignKey(
        Student, on_delete=models.PROTECT, related_name="attendance_records"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRESENT)
    note = models.CharField(max_length=255, blank=True)
    placement = models.ForeignKey("students.StudentEnrolment", null=True, blank=True, on_delete=models.PROTECT)
    arrival_time = models.TimeField(null=True, blank=True)
    minutes_late = models.PositiveSmallIntegerField(null=True, blank=True)
    absence_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "session", "student"], name="uniq_record_per_student_session"
            )
        ]


class AttendancePolicy(TenantScopedModel):
    """Unconfigured means no percentage is asserted for this school."""

    class ExcusedTreatment(models.TextChoices):
        UNCONFIGURED = "", "Not configured"
        EXCLUDE = "exclude", "Exclude excused from denominator"
        ABSENT = "absent", "Include excused as absence"
        PRESENT = "present", "Include excused as attendance"

    excused_treatment = models.CharField(max_length=12, blank=True, choices=ExcusedTreatment.choices, default="")
    late_counts_present = models.BooleanField(null=True, blank=True)
    follow_up_threshold = models.PositiveSmallIntegerField(null=True, blank=True)
    guardian_notifications = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="uniq_attendance_policy_tenant"),
            models.CheckConstraint(condition=models.Q(follow_up_threshold__lte=100), name="attendance_threshold_pct"),
        ]


class StaffAttendance(TenantScopedModel):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        LATE = "late", "Late"
        EXCUSED = "excused", "Excused"
        ON_LEAVE = "on_leave", "On Leave"

    membership = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="attendance_records")
    date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices)
    arrival_time = models.TimeField(null=True, blank=True)
    departure_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-date", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "membership", "date"], name="uniq_staff_attendance_day"),
            models.CheckConstraint(condition=models.Q(status__in=["present", "absent", "late", "excused", "on_leave"]), name="valid_staff_attendance_status"),
        ]

    def clean(self):
        super().clean()
        if self.membership_id:
            from apps.tenancy.models import Role

            member = self.membership
            if member.tenant_id != self.tenant_id:
                raise ValidationError("Staff membership belongs to another school.")
            if member.user.is_superuser or member.role in (Role.GUARDIAN, Role.STUDENT):
                raise ValidationError("Select a school staff membership.")
        if self.arrival_time and self.departure_time and self.departure_time < self.arrival_time:
            raise ValidationError("Departure cannot precede arrival on the attendance day.")

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            from apps.core.context import get_current_tenant

            self.tenant = get_current_tenant()
        self.full_clean()
        return super().save(*args, **kwargs)


class AttendanceNotification(TenantScopedModel):
    """Pending delivery only: no provider or delivery claim is implied."""

    record = models.ForeignKey(AttendanceRecord, on_delete=models.PROTECT, related_name="notifications")
    guardian = models.ForeignKey("students.Guardian", on_delete=models.PROTECT)
    status = models.CharField(max_length=12, default="pending", editable=False)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "record", "guardian"], name="uniq_attendance_notification")]
