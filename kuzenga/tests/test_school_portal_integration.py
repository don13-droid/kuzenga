import pytest
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.urls import reverse

from apps.core.context import tenant_context
from apps.students.services import create_student
from apps.tenancy.models import Membership, Role

from .conftest import make_user

pytestmark = pytest.mark.django_db


def test_school_login_routes_to_dashboard_and_all_navigation_links_resolve(client, admin_a):
    response = client.post(reverse("login"), {"username": admin_a.email, "password": "pass12345!"})
    assert response.status_code == 302 and response.url == "/"
    dashboard = client.get(response.url)
    assert dashboard.status_code == 200
    urls = {item["url"] for item in dashboard.context["nav_items"]}
    assert {"students:list", "admissions:dashboard", "academics:overview", "academics:progression"} <= urls
    for name in urls:
        assert client.get(reverse(name)).status_code == 200


def test_school_owner_and_administrator_admissions_access(client, tenant_a, admin_a):
    owner = make_user(tenant_a, Role.OWNER)
    for person in (owner, admin_a):
        client.force_login(person)
        assert client.get(reverse("admissions:dashboard")).status_code == 200
        assert client.get(reverse("admissions:list")).status_code == 200
        assert client.get(reverse("admissions:create")).status_code == 200


def test_platform_login_does_not_grant_school_admissions_even_with_membership(client, tenant_a):
    person = get_user_model().objects.create_superuser("portal-integration@example.test", "Unused-password-1!")
    Membership.objects.create(user=person, tenant=tenant_a, role=Role.OWNER)
    response = client.post(reverse("platform-login"), {"username": person.email, "password": "Unused-password-1!"})
    assert response.url == reverse("superuser:tenant-directory")
    assert client.get(reverse("admissions:dashboard")).status_code == 403
    assert client.get(reverse("academics:overview")).status_code == 403


def test_school_dashboard_uses_real_tenant_scoped_metrics(client, tenant_a, tenant_b, admin_a):
    with tenant_context(tenant_a):
        create_student(first_name="Own", last_name="Student")
    with tenant_context(tenant_b):
        create_student(first_name="Other", last_name="School")
        create_student(first_name="Another", last_name="School")
    client.force_login(admin_a)
    response = client.get(reverse("dashboard"))
    assert dict(response.context["stats"])["Active learners"] == 1


def test_modules_use_shared_form_fields_without_changing_markup(client, admin_a):
    client.force_login(admin_a)
    routes = [reverse("students:create"), reverse("admissions:create"), reverse("academics:create", args=["subjects"])]
    for url in routes:
        response = client.get(url)
        assert response.status_code == 200
        assert "components/form_fields.html" in [template.name for template in response.templates]
        assert b'csrfmiddlewaretoken' in response.content
        form = response.context["form"]
        assert render_to_string("students/_fields.html", {"form": form}) == render_to_string("admissions/_fields.html", {"form": form})
