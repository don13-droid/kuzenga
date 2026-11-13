from datetime import date
from io import StringIO

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.urls import reverse
from django.utils import timezone

from apps.academics import services
from apps.academics.forms import ClassGroupForm
from apps.academics.models import AcademicYear, ClassGroup, Grade, Subject, SubjectOffering, TeacherAllocation, Term
from apps.core.context import tenant_context
from apps.core.models import AuditEvent
from apps.students import services as student_services
from apps.students.models import Student, StudentEnrolment
from apps.tenancy.models import Membership, Role

from .conftest import make_class, make_user

pytestmark = pytest.mark.django_db


def subject(tenant, code="MATH"):
    with tenant_context(tenant):
        return Subject.objects.create(code=code, name=code)


def offering(group, subj):
    return SubjectOffering(tenant=group.tenant, academic_year=group.academic_year, grade=group.grade,
                            subject=subj, class_group=group)


def another_class(group, name="4B", **values):
    return ClassGroup.objects.create(academic_year=group.academic_year, grade=group.grade, name=name, **values)


def test_year_activation_current_switch_and_history(tenant_a, admin_a):
    group = make_class(tenant_a)
    old = group.academic_year
    with tenant_context(tenant_a):
        term = Term.objects.create(academic_year=old, name="Term 1", start_date=date(2026, 1, 5), end_date=date(2026, 4, 5), is_current=True)
        new = AcademicYear(tenant=tenant_a, name="2027", start_date=date(2027, 1, 1), end_date=date(2027, 12, 31), is_current=True)
        services.save_record(new, actor=admin_a)
        old.refresh_from_db()
        term.refresh_from_db()
        assert old.status == "completed" and not old.is_current and not term.is_current
        assert new.status == "active" and new.is_current
        assert AcademicYear.objects.count() == 2 and Term.objects.count() == 1
        assert AuditEvent.objects.filter(action="academic.period_changed", object_id=str(old.pk)).exists()


def test_overlapping_years_reject_and_roll_back_activation(tenant_a, admin_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        year = AcademicYear(tenant=tenant_a, name="Overlap", start_date=date(2026, 6, 1), end_date=date(2027, 6, 1), is_current=True)
        with pytest.raises(ValidationError):
            services.save_record(year, actor=admin_a)
        group.academic_year.refresh_from_db()
        assert group.academic_year.status == "active" and group.academic_year.is_current


def test_year_and_term_form_edit_round_trip(client, tenant_a, admin_a):
    client.force_login(admin_a)
    values = {"name": "2026", "start_date": "2026-01-01", "end_date": "2026-12-31", "status": "active", "is_current": "on"}
    assert client.post(reverse("academics:create", args=["years"]), values).status_code == 302
    with tenant_context(tenant_a):
        year = AcademicYear.objects.get()
    url = reverse("academics:edit", args=["years", year.pk])
    form = client.get(url).context["form"]
    assert client.post(url, {**values, "name": "Academic 2026", "expected_updated_at": form["expected_updated_at"].value()}).status_code == 302
    terms = {"academic_year": year.pk, "name": "First term", "start_date": "2026-01-05", "end_date": "2026-04-05", "is_current": "on"}
    assert client.post(reverse("academics:create", args=["terms"]), terms).status_code == 302
    with tenant_context(tenant_a):
        assert Term.objects.get().is_current


def test_term_overlap_boundaries_and_current_switch(tenant_a, admin_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        first = Term.objects.create(academic_year=group.academic_year, name="One", start_date=date(2026, 1, 5), end_date=date(2026, 4, 5), is_current=True)
        for beginning, ending in [(date(2026, 4, 1), date(2026, 5, 1)), (date(2025, 12, 1), date(2026, 1, 10))]:
            with pytest.raises(ValidationError):
                services.save_record(Term(tenant=tenant_a, academic_year=group.academic_year, name="Invalid", start_date=beginning, end_date=ending), actor=admin_a)
        second = Term(tenant=tenant_a, academic_year=group.academic_year, name="Two", start_date=date(2026, 5, 1), end_date=date(2026, 8, 1), is_current=True)
        services.save_record(second, actor=admin_a)
        first.refresh_from_db()
        assert not first.is_current and second.is_current


def test_database_period_uniqueness(tenant_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        with pytest.raises(IntegrityError), transaction.atomic():
            AcademicYear.objects.create(name="Another", start_date=date(2027, 1, 1), end_date=date(2027, 12, 31), status="active")
        Term.objects.create(academic_year=group.academic_year, name="One", start_date=date(2026, 1, 1), end_date=date(2026, 4, 1), is_current=True)
        with pytest.raises(IntegrityError), transaction.atomic():
            Term.objects.create(academic_year=group.academic_year, name="Two", start_date=date(2026, 5, 1), end_date=date(2026, 8, 1), is_current=True)


def test_year_shrink_cannot_orphan_term(tenant_a, admin_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        Term.objects.create(academic_year=group.academic_year, name="Late", start_date=date(2026, 10, 1), end_date=date(2026, 12, 20))
        group.academic_year.end_date = date(2026, 11, 30)
        with pytest.raises(ValidationError):
            services.save_record(group.academic_year, actor=admin_a)


def test_class_teacher_validation_and_code_uniqueness(tenant_a, tenant_b, admin_a, teacher_a, admin_b):
    group = make_class(tenant_a)
    teacher = Membership.objects.get(user=teacher_a, tenant=tenant_a)
    foreign = Membership.objects.get(user=admin_b, tenant=tenant_b)
    with tenant_context(tenant_a):
        group.class_teacher = teacher
        group.code = "F4-A"
        services.save_record(group, actor=admin_a)
        for invalid in (foreign, Membership.objects.get(user=admin_a, tenant=tenant_a)):
            group.class_teacher = invalid
            with pytest.raises(ValidationError):
                services.save_record(group, actor=admin_a)
        duplicate = ClassGroup(tenant=tenant_a, academic_year=group.academic_year, grade=group.grade, name="Different", code="F4-A")
        with pytest.raises(ValidationError):
            services.save_record(duplicate, actor=admin_a)


def test_class_capacity_enforced_for_student_registration_and_reactivation(tenant_a, admin_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        group.capacity = 1
        services.save_record(group, actor=admin_a)
        first = student_services.create_student(first_name="First", last_name="One", class_group=group)
        with pytest.raises(ValidationError):
            student_services.create_student(first_name="Second", last_name="One", class_group=group)
        assert Student.objects.count() == 1
        student_services.change_student_status(first, status="suspended", reason="Pause", actor=admin_a)
        student_services.create_student(first_name="Second", last_name="One", class_group=group)
        with pytest.raises(ValidationError):
            student_services.change_student_status(first, status="active", reason="Return", actor=admin_a)


def test_capacity_checks_future_peak_and_prevents_lowering_capacity(tenant_a, admin_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        group.capacity = 1
        services.save_record(group, actor=admin_a)
        first = student_services.create_student(first_name="First", last_name="One")
        second = student_services.create_student(first_name="Second", last_name="Two")
        student_services.enrol_student(first, group, effective_from=date(2026, 12, 1))
        with pytest.raises(ValidationError):
            student_services.enrol_student(second, group, effective_from=date(2026, 11, 1))
        group.capacity = 0
        with pytest.raises(ValidationError):
            services.save_record(group, actor=admin_a)


def test_subjects_school_specific_unique_and_searchable(client, tenant_a, tenant_b, admin_a):
    subject(tenant_b, "BIO")
    client.force_login(admin_a)
    data = {"code": "BIO", "name": "Biology", "description": "Life science", "is_active": "on"}
    assert client.post(reverse("academics:create", args=["subjects"]), data).status_code == 302
    response = client.post(reverse("academics:create", args=["subjects"]), data)
    assert response.context["form"].errors
    response = client.get(reverse("academics:subjects"), {"q": "Life science", "active": "yes"})
    assert len(response.context["page"]) == 1


def test_grade_and_class_offerings_avoid_duplicate_coverage(tenant_a, admin_a):
    group = make_class(tenant_a)
    subj = subject(tenant_a)
    with tenant_context(tenant_a):
        wide = offering(group, subj)
        wide.class_group = None
        services.save_record(wide, actor=admin_a)
        with pytest.raises(ValidationError):
            services.save_record(offering(group, subj), actor=admin_a)
        wide.is_active = False
        services.save_record(wide, actor=admin_a)
        single = offering(group, subj)
        single.is_compulsory = False
        services.save_record(single, actor=admin_a)
        with pytest.raises(ValidationError):
            services.save_record(offering(group, subj), actor=admin_a)


def test_teacher_allocations_validate_compatibility_duplicates_and_deactivation(tenant_a, admin_a, teacher_a):
    group = make_class(tenant_a)
    subj = subject(tenant_a)
    teacher = Membership.objects.get(user=teacher_a)
    with tenant_context(tenant_a):
        course = services.save_record(offering(group, subj), actor=admin_a)
        allocation = TeacherAllocation(tenant=tenant_a, offering=course, class_group=group, teacher=teacher)
        services.save_record(allocation, actor=admin_a)
        term = Term.objects.create(academic_year=group.academic_year, name="First", start_date=date(2026, 1, 1), end_date=date(2026, 4, 1))
        with pytest.raises(ValidationError):
            services.save_record(TeacherAllocation(tenant=tenant_a, offering=course, class_group=group, teacher=teacher, term=term), actor=admin_a)
        other = another_class(group)
        with pytest.raises(ValidationError):
            services.save_record(TeacherAllocation(tenant=tenant_a, offering=course, class_group=other, teacher=teacher), actor=admin_a)
        course.is_active = False
        services.save_record(course, actor=admin_a)
        allocation.refresh_from_db()
        assert not allocation.is_active and TeacherAllocation.objects.count() == 1


def test_subject_deactivation_preserves_and_disables_offerings(tenant_a, admin_a, teacher_a):
    group = make_class(tenant_a)
    subj = subject(tenant_a)
    with tenant_context(tenant_a):
        course = services.save_record(offering(group, subj), actor=admin_a)
        services.save_record(TeacherAllocation(tenant=tenant_a, offering=course, class_group=group, teacher=Membership.objects.get(user=teacher_a)), actor=admin_a)
        subj.is_active = False
        services.save_record(subj, actor=admin_a)
        assert not SubjectOffering.objects.get().is_active and not TeacherAllocation.objects.get().is_active


def test_teacher_only_sees_own_allocations(client, tenant_a, admin_a, teacher_a):
    group = make_class(tenant_a)
    subj = subject(tenant_a)
    other_teacher = make_user(tenant_a, Role.TEACHER, "other-teacher@example.test")
    with tenant_context(tenant_a):
        course = services.save_record(offering(group, subj), actor=admin_a)
        for user in (teacher_a, other_teacher):
            services.save_record(TeacherAllocation(tenant=tenant_a, offering=course, class_group=group, teacher=Membership.objects.get(user=user)), actor=admin_a)
    client.force_login(teacher_a)
    response = client.get(reverse("academics:allocations"))
    assert len(response.context["page"]) == 1 and b"other-teacher@example.test" not in response.content
    assert client.get(reverse("academics:create", args=["allocations"])).status_code == 403
    with tenant_context(tenant_a), pytest.raises(PermissionDenied):
        services.save_record(subj, actor=teacher_a)


@pytest.mark.parametrize("mode", ["promotion", "repetition"])
def test_progression_preserves_history_and_is_repeat_safe(tenant_a, admin_a, mode):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        student = student_services.create_student(first_name="Student", last_name="One", class_group=group)
        year = AcademicYear.objects.create(name="2027", start_date=date(2027, 1, 1), end_date=date(2027, 12, 31), status="planned")
        grade = Grade.objects.create(name="Form 5", level_order=5) if mode == "promotion" else group.grade
        target = ClassGroup.objects.create(academic_year=year, grade=grade, name="A")
        values = dict(students=[student], target_class=target, effective_from=date(2027, 1, 5), mode=mode, reason="Annual progression", actor=admin_a)
        services.progress_students(**values)
        services.progress_students(**values)
        history = list(StudentEnrolment.objects.filter(student=student).order_by("effective_from"))
        assert len(history) == 2 and history[0].effective_to == group.academic_year.end_date
        assert history[1].class_group == target
        assert AuditEvent.objects.filter(action="academic.student_progressed", object_id=str(student.pk)).count() == 1


def test_progression_capacity_failure_rolls_back_whole_batch(tenant_a, admin_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        students = [student_services.create_student(first_name=f"S{i}", last_name="One") for i in range(2)]
        target = another_class(group, capacity=1)
        count = AuditEvent.objects.count()
        with pytest.raises(ValidationError):
            services.progress_students(students=students, target_class=target, effective_from=timezone.localdate(),
                                       mode="initial", reason="Placement", actor=admin_a)
        assert not StudentEnrolment.objects.exists() and AuditEvent.objects.count() == count


def test_placement_rejects_year_date_and_closed_year(tenant_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        student = student_services.create_student(first_name="Student", last_name="One")
        with pytest.raises(ValidationError):
            student_services.enrol_student(student, group, effective_from=date(2027, 1, 1))
        group.academic_year.status = "completed"
        group.academic_year.is_current = False
        group.academic_year.save()
        with pytest.raises(ValidationError):
            student_services.enrol_student(student, group)


def test_tenant_isolation_in_forms_services_and_urls(client, tenant_a, tenant_b, admin_a, admin_b):
    group = make_class(tenant_a)
    foreign = make_class(tenant_b)
    with tenant_context(tenant_a):
        form = ClassGroupForm()
        assert foreign.academic_year not in form.fields["academic_year"].queryset
        with pytest.raises(ValidationError):
            services.save_record(offering(group, subject(tenant_b)), actor=admin_a)
        with pytest.raises(ValidationError):
            services.save_record(foreign, actor=admin_a)
    client.force_login(admin_a)
    assert client.get(reverse("academics:class-detail", args=[foreign.pk])).status_code == 404
    assert client.get(reverse("academics:edit", args=["classes", foreign.pk])).status_code == 404
    response = client.get(reverse("academics:classes"), {"academic_year": foreign.academic_year_id})
    assert response.context["filters"].errors


def test_dashboard_and_class_curriculum_rendering(client, tenant_a, admin_a, teacher_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        group.capacity = 1
        group.save()
        student_services.create_student(first_name="Roster", last_name="Learner", class_group=group)
        services.save_record(offering(group, subject(tenant_a)), actor=admin_a)
    client.force_login(admin_a)
    response = client.get(reverse("academics:overview"))
    assert response.status_code == 200 and response.context["placement_count"] == 1
    assert len(response.context["near_capacity"]) == 1
    response = client.get(reverse("academics:class-detail", args=[group.pk]))
    assert b"MATH" in response.content and b"Roster Learner" in response.content
    response = client.get(reverse("academics:classes"))
    assert b"100%" in response.content
    client.force_login(teacher_a)
    assert client.get(reverse("academics:progression")).status_code == 403


# SQLite needs constraint toggles outside atomic; PostgreSQL avoids guard-blocked flush.
@pytest.mark.django_db(transaction=connection.vendor == "sqlite")
def test_migration_does_not_rebuild_existing_tables():
    output = StringIO()
    call_command("sqlmigrate", "academics", "0004", stdout=output)
    assert "DROP TABLE" not in output.getvalue() and "new__" not in output.getvalue()
