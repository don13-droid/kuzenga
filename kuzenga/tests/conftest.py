from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.academics.models import AcademicYear, ClassGroup, Grade
from apps.core.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant
from apps.tenancy.services import activate_plan

User = get_user_model()


@pytest.fixture(autouse=True)
def catalogue(db):
    call_command("seed_catalog")


def make_tenant(slug, plan="standard"):
    from apps.tenancy.models import Plan

    tenant = Tenant.objects.create(name=f"School {slug}", slug=slug, status=Tenant.Status.ACTIVE)
    activate_plan(tenant, Plan.objects.get(code=plan))
    return tenant


def make_user(tenant, role, email=None):
    user = User.objects.create_user(email or f"{role}@{tenant.slug}.test", "pass12345!")
    Membership.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_class(tenant, name="4A"):
    with tenant_context(tenant):
        year = AcademicYear.objects.create(
            name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), is_current=True
        )
        grade = Grade.objects.create(name="Form 4", level_order=4)
        return ClassGroup.objects.create(academic_year=year, grade=grade, name=name)


@pytest.fixture
def tenant_a(db):
    return make_tenant("a")


@pytest.fixture
def tenant_b(db):
    return make_tenant("b")


@pytest.fixture
def admin_a(tenant_a):
    return make_user(tenant_a, Role.ADMIN)


@pytest.fixture
def teacher_a(tenant_a):
    return make_user(tenant_a, Role.TEACHER)


@pytest.fixture
def admin_b(tenant_b):
    return make_user(tenant_b, Role.ADMIN)
