from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import audit
from apps.students.models import StudentEnrolment

from .models import AttendanceRecord, AttendanceSession


def enrolled_on(class_group, on_date):
    return (
        StudentEnrolment.objects.filter(
            class_group=class_group, effective_from__lte=on_date, student__status="active"
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .select_related("student")
    )


@transaction.atomic
def open_register(class_group, on_date) -> AttendanceSession:
    session, _ = AttendanceSession.objects.get_or_create(class_group=class_group, date=on_date)
    if session.status == AttendanceSession.Status.OPEN:
        existing = set(session.records.values_list("student_id", flat=True))
        for enrolment in enrolled_on(class_group, on_date):
            if enrolment.student_id not in existing:
                AttendanceRecord.objects.create(session=session, student=enrolment.student)
    return session


@transaction.atomic
def submit_register(
    session, statuses: dict, notes: dict, *, actor, valid_statuses=None, request=None
) -> AttendanceSession:
    if session.status != AttendanceSession.Status.OPEN:
        raise ValueError("Register already submitted")
    valid = set(AttendanceRecord.Status.values if valid_statuses is None else valid_statuses)
    for record in session.records.all():
        status = statuses.get(str(record.student_id), record.status)
        if status not in valid:
            raise ValueError(f"Invalid status: {status}")
        record.status = status
        record.note = notes.get(str(record.student_id), "")[:255]
        record.save(update_fields=["status", "note", "updated_at"])
    session.status = AttendanceSession.Status.SUBMITTED
    session.submitted_by = actor
    session.submitted_at = timezone.now()
    session.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
    audit.record("attendance.submitted", actor=actor, obj=session, request=request, date=session.date)
    return session


# Module 09 foundation services; existing register services remain compatible.
def attendance_percentage(counts, policy):
    """Only confirmed statuses count; missing marks never become absences."""
    if policy is None or not policy.excused_treatment or policy.late_counts_present is None:
        return None
    present = counts.get("present", 0)
    late = counts.get("late", 0)
    absent = counts.get("absent", 0)
    excused = counts.get("excused", 0)
    numerator = present + (late if policy.late_counts_present else 0)
    denominator = present + late + absent
    if policy.excused_treatment != "exclude":
        denominator += excused
    if policy.excused_treatment == "present":
        numerator += excused
    return round(100 * numerator / denominator, 2) if denominator else None


def _attendance_administrator(actor):
    from django.core.exceptions import PermissionDenied

    from apps.core.context import get_current_tenant
    from apps.tenancy.models import Membership, Role
    from apps.tenancy.services import has_module

    tenant = get_current_tenant()
    if tenant is None or actor is None or not actor.is_active or actor.is_superuser:
        raise PermissionDenied
    if not has_module(tenant, "attendance") or not Membership.objects.filter(
        tenant=tenant, user=actor, status="active", role__in=[Role.OWNER, Role.ADMIN]
    ).exists():
        raise PermissionDenied
    return tenant


@transaction.atomic
def record_staff_attendance(*, membership, on_date, status, actor, reason="", note="",
                            arrival_time=None, departure_time=None, correction_reason="", request=None):
    from django.core.exceptions import ValidationError

    from apps.tenancy.models import Membership

    from .models import StaffAttendance

    tenant = _attendance_administrator(actor)
    # Membership is a global model: explicitly resolve its tenant before writing.
    member = Membership.objects.select_for_update().get(pk=membership.pk, tenant=tenant)
    record = StaffAttendance.objects.select_for_update().filter(membership=member, date=on_date).first()
    if record and not correction_reason.strip():
        raise ValidationError("A correction reason is required for existing staff attendance.")
    created = record is None
    if created:
        record = StaffAttendance(tenant=tenant, membership=member, date=on_date)
    before = record.status if not created else None
    record.status, record.reason, record.note = status, reason, note
    record.arrival_time, record.departure_time = arrival_time, departure_time
    record.recorded_by = actor
    record.save()
    audit.record("attendance.staff_recorded" if created else "attendance.staff_corrected",
                 actor=actor, obj=record, request=request,
                 before_status=before, after_status=status,
                 correction_reason=correction_reason[:255] if not created else "")
    return record


@transaction.atomic
def queue_absence_notifications(record, *, actor, request=None):
    from django.core.exceptions import ValidationError

    from apps.students.models import StudentGuardian

    from .models import AttendanceNotification, AttendancePolicy

    _attendance_administrator(actor)
    record = AttendanceRecord.objects.select_for_update().select_related("session").get(pk=record.pk)
    if record.status != AttendanceRecord.Status.ABSENT or record.session.status != AttendanceSession.Status.SUBMITTED:
        raise ValidationError("Only confirmed absent records can be queued for notification.")
    if not AttendancePolicy.objects.filter(guardian_notifications=True).exists():
        raise ValidationError("Guardian attendance notifications are not enabled for this school.")
    notifications = []
    for link in StudentGuardian.objects.filter(student=record.student).select_related("guardian"):
        if not (link.guardian.email or link.guardian.phone):
            continue
        notification, created = AttendanceNotification.objects.get_or_create(
            record=record, guardian=link.guardian, defaults={"requested_by": actor}
        )
        if created:
            audit.record("attendance.notification_pending", actor=actor, obj=notification,
                         request=request, attendance_record=record.pk)
        notifications.append(notification)
    return notifications
