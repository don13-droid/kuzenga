import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.tenancy.middleware import SESSION_KEY
from apps.tenancy.models import Membership, Role


@pytest.fixture
def student_user(tenant_a):
    user = get_user_model().objects.create_user("student-login@example.test", "Unused-password-1!")
    Membership.objects.create(user=user, tenant=tenant_a, role=Role.STUDENT)
    return user


@pytest.mark.django_db
def test_student_can_sign_in_to_school_portal_and_sign_out(client, student_user, tenant_a):
    response = client.post(reverse("login"), {
        "username": student_user.email, "password": "Unused-password-1!",
    })
    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    dashboard = client.get(response.url)
    assert dashboard.status_code == 200
    assert dashboard.context["tenant"] == tenant_a
    assert dashboard.wsgi_request.membership.role == Role.STUDENT
    assert dashboard.context["stats"] == []
    assert b"Active learners" not in dashboard.content
    assert b"No modules are active" not in dashboard.content
    assert b"No workspaces are available for this account." in dashboard.content
    logout = client.post(reverse("logout"))
    assert logout.url == reverse("login")
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["students:list", "academics:overview", "superuser:tenant-directory"])
def test_student_cannot_access_staff_or_platform_workspaces(client, student_user, route):
    client.force_login(student_user)
    assert client.get(reverse(route)).status_code == 403


@pytest.mark.django_db
def test_student_cannot_authenticate_through_platform_login(client, student_user):
    response = client.post(reverse("platform-login"), {
        "username": student_user.email, "password": "Unused-password-1!",
    })
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_student_session_cannot_select_another_school(client, student_user, tenant_a, tenant_b):
    client.force_login(student_user)
    session = client.session
    session[SESSION_KEY] = str(tenant_b.pk)
    session.save()
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert response.wsgi_request.tenant == tenant_a
    assert client.session[SESSION_KEY] == str(tenant_a.pk)


@pytest.mark.django_db
def test_suspended_student_membership_does_not_open_school_dashboard(client, student_user):
    Membership.objects.filter(user=student_user).update(status=Membership.Status.SUSPENDED)
    client.force_login(student_user)
    response = client.get(reverse("dashboard"))
    assert response.url == reverse("tenancy:select")


@pytest.mark.django_db
def test_inactive_student_cannot_sign_in(client, student_user):
    student_user.is_active = False
    student_user.save(update_fields=["is_active"])
    response = client.post(reverse("login"), {
        "username": student_user.email, "password": "Unused-password-1!",
    })
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
