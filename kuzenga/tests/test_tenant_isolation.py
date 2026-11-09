import pytest

from apps.academics.models import Subject
from apps.core.context import tenant_context
from apps.core.exceptions import TenantContextMissing, TenantMismatch
from apps.students import services
from apps.students.models import Student

from .conftest import make_class


def test_no_tenant_context_returns_nothing(tenant_a):
    with tenant_context(tenant_a):
        Subject.objects.create(code="MAT", name="Maths")
    assert Subject.objects.count() == 0  # fail closed


def test_write_without_tenant_context_is_refused(db):
    with pytest.raises(TenantContextMissing):
        Subject.objects.create(code="MAT", name="Maths")


def test_queries_are_scoped_per_tenant(tenant_a, tenant_b):
    with tenant_context(tenant_a):
        Subject.objects.create(code="MAT", name="Maths")
    with tenant_context(tenant_b):
        assert Subject.objects.count() == 0
        Subject.objects.create(code="MAT", name="Maths")  # same code allowed in another tenant
        assert Subject.objects.count() == 1


def test_cannot_save_record_of_other_tenant(tenant_a, tenant_b):
    with tenant_context(tenant_a):
        subject = Subject.objects.create(code="MAT", name="Maths")
    with tenant_context(tenant_b), pytest.raises(TenantMismatch):
        subject.name = "Hacked"
        subject.save()


def test_cross_tenant_foreign_key_is_refused(tenant_a, tenant_b):
    class_a = make_class(tenant_a)
    with tenant_context(tenant_b):
        student = services.create_student(first_name="Tariro", last_name="Moyo")
        with pytest.raises(TenantMismatch):
            from apps.students.models import StudentEnrolment

            StudentEnrolment(
                student=student, class_group=class_a, effective_from="2026-01-05"
            ).save()


def test_admission_numbers_unique_and_per_tenant(tenant_a, tenant_b):
    with tenant_context(tenant_a):
        n1 = services.create_student(first_name="A", last_name="One").admission_number
        n2 = services.create_student(first_name="B", last_name="Two").admission_number
    with tenant_context(tenant_b):
        n3 = services.create_student(first_name="C", last_name="Three").admission_number
    assert n1 != n2
    assert n1 == n3  # each school has its own sequence
    with tenant_context(tenant_a):
        assert Student.objects.count() == 2
