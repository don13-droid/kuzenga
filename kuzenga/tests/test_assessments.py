from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.academics.models import AssessmentCategory, GradeBoundary, Subject, Term
from apps.assessments.models import Assessment, Examination, Mark, PublishedResult, ResultPolicy
from apps.assessments.services import save_marks, subject_total, transition
from apps.core.context import tenant_context
from apps.students.models import Student, StudentEnrolment
from apps.tenancy.models import Membership
from tests.conftest import make_class


@pytest.fixture
def assessment_data(tenant_a, admin_a):
    with tenant_context(tenant_a):
        classroom = make_class(tenant_a)
        term = Term.objects.create(
            academic_year=classroom.academic_year,
            name="Term 1",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 30),
        )
        subject = Subject.objects.create(code="MATH", name="Mathematics")
        category = AssessmentCategory.objects.create(name="Test", kind="continuous", maximum_marks=100, pass_marks=50)
        policy = ResultPolicy.objects.create(name="School policy", continuous_weight=100, examination_weight=0)
        assessment = Assessment.objects.create(
            title="First test",
            kind="test",
            category=category,
            term=term,
            class_group=classroom,
            subject=subject,
            policy=policy,
            date=date(2026, 2, 1),
            maximum_marks=100,
        )
        student = Student.objects.create(first_name="Ada", last_name="Test", admission_number="A1")
        StudentEnrolment.objects.create(student=student, class_group=classroom, effective_from=date(2026, 1, 1))
        GradeBoundary.objects.create(grade="Pass", minimum_percent=50, maximum_percent=100, is_pass=True)
        GradeBoundary.objects.create(grade="Fail", minimum_percent=0, maximum_percent=Decimal("49.99"), is_pass=False)
    return assessment, student, Membership.objects.get(user=admin_a, tenant=tenant_a)


@pytest.mark.django_db
def test_workflow_snapshot_and_decimal(tenant_a, assessment_data):
    assessment, student, member = assessment_data
    with tenant_context(tenant_a):
        save_marks(assessment, [{"student": student.pk, "score": Decimal("73.25"), "comment": "Good progress"}], member)
        for state in ["submitted", "under_review", "approved", "published"]:
            transition(assessment, state, member)
        result = PublishedResult.objects.get()
        assert result.snapshot["percent"] == "73.25"
        assert subject_total([result]) == Decimal("73.25")
        with pytest.raises(ValidationError):
            save_marks(assessment, [{"student": student.pk, "score": 20}], member)
        with pytest.raises(ValidationError):
            transition(assessment, "draft", member, "Change")
        with pytest.raises(ValidationError):
            result.save()


@pytest.mark.django_db
def test_atomic_validation_and_duplicate_prevention(tenant_a, assessment_data):
    assessment, student, member = assessment_data
    with tenant_context(tenant_a):
        with pytest.raises(ValidationError):
            save_marks(assessment, [{"student": student.pk, "score": 101}], member)
        assert not Mark.objects.exists()
        with pytest.raises(ValidationError):
            save_marks(assessment, [{"student": student.pk, "score": 10}] * 2, member)
        with pytest.raises(ValidationError):
            transition(assessment, "submitted", member)
        with pytest.raises(ValidationError):
            transition(assessment, "published", member)


@pytest.mark.django_db
def test_tenant_and_teacher_denials(tenant_a, tenant_b, teacher_a, assessment_data):
    assessment, student, member = assessment_data
    with tenant_context(tenant_b):
        assert not Assessment.objects.exists()
        with pytest.raises(PermissionDenied):
            save_marks(assessment, [], member)
    with tenant_context(tenant_a):
        teacher = Membership.objects.get(user=teacher_a, tenant=tenant_a)
        with pytest.raises(PermissionDenied):
            save_marks(assessment, [{"student": student.pk, "score": 20}], teacher)
        with pytest.raises(PermissionDenied):
            transition(assessment, "under_review", teacher)


@pytest.mark.django_db
def test_exemption_and_review_correction(tenant_a, assessment_data):
    assessment, student, member = assessment_data
    with tenant_context(tenant_a):
        save_marks(assessment, [{"student": student.pk, "score": None, "exempt": True}], member)
        transition(assessment, "submitted", member)
        with pytest.raises(ValidationError):
            transition(assessment, "draft", member)
        transition(assessment, "draft", member, "Check exemption evidence")
        for state in ["submitted", "under_review", "approved", "published"]:
            transition(assessment, state, member)
        assert PublishedResult.objects.get().snapshot["exempt"]
        assert subject_total(list(PublishedResult.objects.all())) is None


@pytest.mark.django_db
def test_screens_and_exports(client, tenant_a, admin_a, assessment_data):
    assessment, student, member = assessment_data
    client.force_login(admin_a)
    session = client.session
    session["active_tenant_id"] = str(tenant_a.pk)
    session.save()
    for url in [
        "/assessments/",
        "/assessments/new/",
        "/assessments/policies/new/",
        f"/assessments/{assessment.pk}/",
        "/assessments/results/",
        "/assessments/analytics/",
    ]:
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
    with tenant_context(tenant_a):
        save_marks(assessment, [{"student": student.pk, "score": 90}], member)
        for state in ["submitted", "under_review", "approved", "published"]:
            transition(assessment, state, member)
    response = client.get(f"/assessments/{assessment.pk}/export.csv")
    assert response.status_code == 200
    assert b"90.00" in response.content
    response = client.get(f"/assessments/students/{student.pk}/terms/{assessment.term_id}/report.pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-1.4")


@pytest.mark.django_db
def test_examination_clashes(tenant_a, assessment_data):
    assessment, student, member = assessment_data
    with tenant_context(tenant_a):
        assessment.kind = "examination"
        assessment.save()
        start = datetime(2026, 2, 1, 8, tzinfo=timezone.utc)
        Examination.objects.create(
            assessment=assessment, starts_at=start, ends_at=start + timedelta(hours=2), room="Hall", invigilator=member
        )
        assessment.pk = None
        assessment.title = "Second examination"
        assessment.save()
        with pytest.raises(ValidationError):
            Examination.objects.create(
                assessment=assessment,
                starts_at=start,
                ends_at=start + timedelta(hours=1),
                room="Hall",
                invigilator=member,
            )


def test_weighted_components_and_competition_ties():
    from types import SimpleNamespace

    from apps.assessments.services import competition_rank

    def result(student, component, percent, exempt=False):
        return SimpleNamespace(
            student_id=student,
            assessment=SimpleNamespace(subject_id="math"),
            snapshot={
                "component": component,
                "percent": str(percent),
                "weight": "1",
                "exempt": exempt,
                "policy": {"continuous": "40", "examination": "60", "rankings": True},
            },
        )

    first = [result("a", "continuous", 80), result("a", "examination", 60)]
    assert subject_total(first) == Decimal("68.00")
    assert subject_total(first[:1]) is None
    assert subject_total([first[0], result("a", "examination", 0, True)]) == Decimal("80.00")
    peers = first + [
        result("b", "continuous", 80),
        result("b", "examination", 60),
        result("c", "continuous", 50),
        result("c", "examination", 50),
    ]
    assert competition_rank(peers, "a") == 1
    assert competition_rank(peers, "b") == 1
    assert competition_rank(peers, "c") == 3


@pytest.mark.django_db
def test_http_cross_tenant_and_unallocated_teacher(client, tenant_a, admin_b, teacher_a, assessment_data):
    assessment, student, member = assessment_data
    client.force_login(admin_b)
    for suffix in ["", "schedule/", "export.csv"]:
        assert client.get(f"/assessments/{assessment.pk}/{suffix}").status_code == 404
    client.force_login(teacher_a)
    assert client.get(f"/assessments/{assessment.pk}/").status_code == 404
    assert client.get("/assessments/policies/new/").status_code == 403


@pytest.mark.django_db
def test_publication_queryset_immutable(tenant_a, assessment_data):
    assessment, student, member = assessment_data
    with tenant_context(tenant_a):
        with pytest.raises(ValidationError):
            PublishedResult.objects.all().update(snapshot={})
        with pytest.raises(ValidationError):
            PublishedResult.objects.all().delete()


@pytest.mark.django_db
def test_allocated_teacher_can_mark_but_not_approve(tenant_a, teacher_a, assessment_data):
    from apps.academics.models import SubjectOffering, TeacherAllocation

    assessment, student, admin = assessment_data
    teacher = Membership.objects.get(user=teacher_a, tenant=tenant_a)
    with tenant_context(tenant_a):
        offering = SubjectOffering.objects.create(
            academic_year=assessment.term.academic_year,
            subject=assessment.subject,
            grade=assessment.class_group.grade,
            class_group=assessment.class_group,
        )
        TeacherAllocation.objects.create(
            offering=offering, class_group=assessment.class_group, teacher=teacher, term=assessment.term
        )
        save_marks(assessment, [{"student": student.pk, "score": 50}], teacher)
        transition(assessment, "submitted", teacher)
        with pytest.raises(PermissionDenied):
            transition(assessment, "under_review", teacher)


@pytest.mark.django_db
def test_invigilator_choices_and_validation_are_tenant_scoped(tenant_a, tenant_b, admin_b, assessment_data):
    from apps.assessments.forms import ExaminationForm

    assessment, student, member = assessment_data
    foreign_member = Membership.objects.get(user=admin_b, tenant=tenant_b)
    with tenant_context(tenant_a):
        choices = ExaminationForm().fields["invigilator"].queryset
        assert not choices.filter(pk=foreign_member.pk).exists()
        assert choices.filter(pk=member.pk).exists()
        assessment.kind = "examination"
        assessment.save()
        start = datetime(2026, 2, 1, 8, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            Examination.objects.create(
                assessment=assessment,
                starts_at=start,
                ends_at=start + timedelta(hours=1),
                room="Hall",
                invigilator=foreign_member,
            )
