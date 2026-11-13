from datetime import date, time

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.attendance.models import (
    AttendanceNotification,
    AttendancePolicy,
    AttendanceRecord,
    AttendanceSession,
    StaffAttendance,
)
from apps.attendance.services import attendance_percentage, queue_absence_notifications, record_staff_attendance
from apps.core.context import tenant_context
from apps.core.models import AuditEvent
from apps.students.models import Guardian, StudentGuardian
from apps.students.services import create_student
from apps.tenancy.models import Membership, Role

from .conftest import make_class, make_user

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('treatment,late,expected', [('exclude', True, 75), ('absent', True, 60), ('present', True, 80), ('exclude', False, 50)])
def test_school_policy_calculation(treatment, late, expected):
    policy = AttendancePolicy(excused_treatment=treatment, late_counts_present=late)
    assert attendance_percentage({'present': 2, 'late': 1, 'absent': 1, 'excused': 1, 'unmarked': 20}, policy) == expected
    assert attendance_percentage({}, policy) is None


def test_unconfigured_policy_has_no_percentage():
    assert attendance_percentage({'present': 5}, None) is None
    assert attendance_percentage({'present': 5}, AttendancePolicy()) is None


def test_staff_record_correction_and_audit(tenant_a, admin_a, teacher_a):
    member = Membership.objects.get(user=teacher_a, tenant=tenant_a)
    with tenant_context(tenant_a):
        row = record_staff_attendance(membership=member, on_date=date(2026, 11, 9), status='late', actor=admin_a, arrival_time=time(8, 30))
        with pytest.raises(ValidationError):
            record_staff_attendance(membership=member, on_date=row.date, status='present', actor=admin_a)
        corrected = record_staff_attendance(membership=member, on_date=row.date, status='present', actor=admin_a, correction_reason='Register entry reviewed')
        assert corrected.pk == row.pk
        assert StaffAttendance.objects.count() == 1
        assert AuditEvent.objects.filter(tenant=tenant_a, action='attendance.staff_corrected').exists()


def test_staff_cannot_cross_tenants_or_self_authorise(tenant_a, tenant_b, admin_a, teacher_a):
    other = make_user(tenant_b, Role.STAFF)
    member = Membership.objects.get(user=other)
    with tenant_context(tenant_a):
        with pytest.raises(Membership.DoesNotExist):
            record_staff_attendance(membership=member, on_date=date.today(), status='present', actor=admin_a)
        with pytest.raises(PermissionDenied):
            record_staff_attendance(membership=member, on_date=date.today(), status='present', actor=teacher_a)
        assert not StaffAttendance.objects.exists()


def test_staff_rejects_guardian_and_bad_times(tenant_a, admin_a, teacher_a):
    guardian = make_user(tenant_a, Role.GUARDIAN)
    with tenant_context(tenant_a):
        for member, arrival, departure in [(Membership.objects.get(user=guardian), None, None), (Membership.objects.get(user=teacher_a), time(10), time(9))]:
            with pytest.raises(ValidationError):
                record_staff_attendance(membership=member, on_date=date.today(), status='present', actor=admin_a, arrival_time=arrival, departure_time=departure)


def test_staff_day_uniqueness(tenant_a, admin_a):
    with tenant_context(tenant_a):
        member = Membership.objects.get(user=admin_a)
        row = StaffAttendance.objects.create(membership=member, date=date.today(), status='present', recorded_by=admin_a)
        with pytest.raises(ValidationError):
            StaffAttendance.objects.create(membership=member, date=row.date, status='absent', recorded_by=admin_a)


def test_pending_notification_deduplication(tenant_a, admin_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        student = create_student(first_name='Attendance', last_name='Test')
        guardian = Guardian.objects.create(first_name='Guardian', last_name='Test', email='guardian@example.test')
        StudentGuardian.objects.create(student=student, guardian=guardian)
        session = AttendanceSession.objects.create(class_group=group, date=date(2026, 11, 9), status='submitted')
        record = AttendanceRecord.objects.create(session=session, student=student, status='absent')
        with pytest.raises(ValidationError):
            queue_absence_notifications(record, actor=admin_a)
        AttendancePolicy.objects.create(guardian_notifications=True)
        first = queue_absence_notifications(record, actor=admin_a)
        second = queue_absence_notifications(record, actor=admin_a)
        assert first[0].pk == second[0].pk
        assert AttendanceNotification.objects.count() == 1
        assert first[0].status == 'pending'
        assert AuditEvent.objects.filter(tenant=tenant_a, action='attendance.notification_pending').count() == 1


def test_policy_threshold_database_constraint(tenant_a):
    with tenant_context(tenant_a), pytest.raises(IntegrityError), transaction.atomic():
        AttendancePolicy.objects.create(follow_up_threshold=101)


def test_platform_user_is_denied_even_with_school_membership(tenant_a):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_superuser('attendance-platform@example.test', 'Unused-test-password!')
    member = Membership.objects.create(user=user, tenant=tenant_a, role=Role.OWNER)
    with tenant_context(tenant_a), pytest.raises(PermissionDenied):
        record_staff_attendance(membership=member, on_date=date.today(), status='present', actor=user)


def test_staff_records_are_invisible_outside_school(tenant_a, tenant_b, admin_a):
    member = Membership.objects.get(user=admin_a)
    with tenant_context(tenant_a):
        record_staff_attendance(membership=member, on_date=date.today(), status='present', actor=admin_a)
        assert StaffAttendance.objects.count() == 1
    with tenant_context(tenant_b):
        assert not StaffAttendance.objects.exists()
    assert not StaffAttendance.objects.exists()
