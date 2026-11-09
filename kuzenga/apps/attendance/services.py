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
