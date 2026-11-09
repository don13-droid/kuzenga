from collections import defaultdict
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.core.context import get_current_tenant
from apps.tenancy.models import Membership, Role

TEACHING_ROLES = (Role.TEACHER, Role.HOD)
TERMINAL_YEAR_STATUSES = ("closed", "completed", "archived")


def validate_teacher(teacher, tenant_id):
    if teacher and (teacher.tenant_id != tenant_id or teacher.status != Membership.Status.ACTIVE
                    or teacher.role not in TEACHING_ROLES or not teacher.user.is_active or teacher.user.is_superuser):
        raise ValidationError("Choose an active teacher or head of department from this school.")


def validate_related(instance, *fields):
    for field in fields:
        if getattr(instance, f"{field}_id") and getattr(instance, field).tenant_id != instance.tenant_id:
            raise ValidationError({field: "The related record must belong to this school."})


def class_peak(class_group, *, from_date=None, exclude_student=None):
    """Maximum active-student occupancy over a dated portion of a class's year."""
    from apps.students.models import StudentEnrolment

    start = from_date or class_group.academic_year.start_date
    end = class_group.academic_year.end_date
    records = StudentEnrolment.objects.filter(class_group=class_group, student__status="active",
                                              effective_from__lte=end).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=start)
    )
    if exclude_student is not None:
        records = records.exclude(student=exclude_student)
    changes = defaultdict(int)
    for beginning, ending in records.values_list("effective_from", "effective_to"):
        beginning, ending = max(start, beginning), min(end, ending or end)
        if ending >= beginning:
            changes[beginning] += 1
            changes[ending + timedelta(days=1)] -= 1
    count = peak = 0
    for day in sorted(changes):
        count += changes[day]
        peak = max(peak, count)
    return peak


def validate_placement(student, class_group, effective_from):
    tenant = get_current_tenant()
    if not tenant or student.tenant_id != tenant.pk or class_group.tenant_id != tenant.pk:
        raise ValidationError("Student and class must belong to the active school.")
    year = class_group.academic_year
    if not class_group.is_active or not class_group.grade.is_active or year.status in TERMINAL_YEAR_STATUSES:
        raise ValidationError("Choose an available class, grade and academic year.")
    if not year.start_date <= effective_from <= year.end_date:
        raise ValidationError("Placement must start within the class's academic year.")
    if class_group.capacity is not None and class_peak(class_group, from_date=effective_from, exclude_student=student) >= class_group.capacity:
        raise ValidationError("This class has no remaining capacity for the requested period.")
