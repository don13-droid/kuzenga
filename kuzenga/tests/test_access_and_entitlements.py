from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.core.context import tenant_context
from apps.students import services
from apps.tenancy.models import Entitlement, Plan, Role
from apps.tenancy.services import activate_plan, has_module, suspend_tenant_access

from .conftest import make_tenant, make_user


def login(client, user):
    client.force_login(user)


def test_idor_other_tenant_student_returns_404(client, tenant_a, tenant_b, admin_a):
    with tenant_context(tenant_b):
        other = services.create_student(first_name="Secret", last_name="Learner")
    login(client, admin_a)
    assert client.get(reverse("students:detail", args=[other.pk])).status_code == 404


def test_list_only_shows_own_tenant(client, tenant_a, tenant_b, admin_a):
    with tenant_context(tenant_a):
        services.create_student(first_name="Mine", last_name="Learner")
    with tenant_context(tenant_b):
        services.create_student(first_name="Theirs", last_name="Learner")
    login(client, admin_a)
    html = client.get(reverse("students:list")).content.decode()
    assert "Mine" in html and "Theirs" not in html


def test_unentitled_module_is_blocked_server_side(client):
    starter = make_tenant("starter", plan="starter")  # no attendance module
    user = make_user(starter, Role.ADMIN)
    login(client, user)
    resp = client.get(reverse("attendance:today"))
    assert resp.status_code == 403
    assert b"not included in your plan" in resp.content


def test_expired_entitlement_is_blocked(client, tenant_a, admin_a):
    Entitlement.objects.filter(tenant=tenant_a, module_id="students").update(
        valid_until=timezone.now() - timedelta(days=1)
    )
    assert not has_module(tenant_a, "students")
    login(client, admin_a)
    assert client.get(reverse("students:list")).status_code == 403


def test_suspension_revokes_access(client, tenant_a, admin_a):
    suspend_tenant_access(tenant_a, reason="non-payment")
    login(client, admin_a)
    assert client.get(reverse("students:list")).status_code == 403


def test_teacher_cannot_create_students_but_admin_can(client, tenant_a, admin_a, teacher_a):
    login(client, teacher_a)
    assert client.get(reverse("students:create")).status_code == 403
    assert (
        client.post(reverse("students:create"), {"first_name": "X", "last_name": "Y"}).status_code
        == 403
    )
    client.logout()
    login(client, admin_a)
    resp = client.post(reverse("students:create"), {"first_name": "Rudo", "last_name": "Chikwanha"})
    assert resp.status_code == 302


def test_user_without_membership_gets_no_tenant_access(client, tenant_a, db):
    from django.contrib.auth import get_user_model

    outsider = get_user_model().objects.create_user("outsider@x.test", "pass12345!")
    login(client, outsider)
    resp = client.get(reverse("students:list"))
    assert resp.status_code == 302 and resp.url == reverse("tenancy:select")


def test_user_cannot_switch_to_tenant_without_membership(client, tenant_a, tenant_b, admin_a):
    login(client, admin_a)
    client.post(reverse("tenancy:select"), {"tenant": str(tenant_b.pk)})
    with tenant_context(tenant_b):
        services.create_student(first_name="Hidden", last_name="Learner")
    html = client.get(reverse("students:list")).content.decode()
    assert "Hidden" not in html


def test_plan_activation_grants_plan_modules(tenant_a):
    codes = set(Plan.objects.get(code="standard").modules.values_list("code", flat=True))
    assert all(has_module(tenant_a, c) for c in codes)
    assert not has_module(tenant_a, "finance")
    sub = activate_plan(tenant_a, Plan.objects.get(code="professional"))
    assert has_module(tenant_a, "finance") and sub.status == "active"
