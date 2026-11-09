import csv
from datetime import date
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import AcademicYear, ClassGroup, Grade
from apps.core import audit
from apps.core.context import tenant_context
from apps.core.models import AuditEvent
from apps.students.models import Student
from apps.tenancy.models import Membership, Plan, Role, Subscription, Tenant

User = get_user_model()


def make_tenant(name, slug, status=Tenant.Status.ACTIVE):
    return Tenant.objects.create(name=name, slug=slug, status=status)


def make_superuser():
    return User.objects.create_superuser("platform@example.test", "pass12345!")


@pytest.mark.django_db
def test_directory_requires_authenticated_platform_superuser(client, admin_a):
    url = reverse("superuser:tenant-directory")
    assert client.get(url).status_code == 302

    client.force_login(admin_a)
    assert client.get(url).status_code == 403


@pytest.mark.django_db
def test_superuser_can_view_directory_and_database_metrics(client, tenant_a, tenant_b):
    Tenant.objects.filter(pk=tenant_a.pk).update(status=Tenant.Status.ACTIVE)
    pending = make_tenant("Pending School", "pending-school", Tenant.Status.TRIAL)
    suspended = make_tenant("Suspended School", "suspended-school", Tenant.Status.SUSPENDED)
    plan = Plan.objects.get(code="standard")
    Subscription.objects.create(
        tenant=tenant_a,
        plan=plan,
        status=Subscription.Status.ACTIVE,
        current_period_end=timezone.now() + timezone.timedelta(days=14),
    )

    client.force_login(make_superuser())
    response = client.get(reverse("superuser:tenant-directory"))

    assert response.status_code == 200
    metrics = response.context["metrics"]
    assert metrics == {
        "total_tenants": 4,
        "active_tenants": 2,
        "pending_tenants": 1,
        "suspended_tenants": 1,
        "expiring_soon": 2,
    }
    assert pending.name in response.content.decode()
    assert suspended.name in response.content.decode()


@pytest.mark.django_db
def test_directory_search_matches_school_name_and_identifier(client):
    make_tenant("Greenwood High", "greenwood-code")
    make_tenant("Other School", "other-school")
    client.force_login(make_superuser())

    by_name = client.get(reverse("superuser:tenant-directory"), {"q": "Greenwood"})
    by_code = client.get(reverse("superuser:tenant-directory"), {"q": "greenwood-code"})

    assert [tenant.slug for tenant in by_name.context["tenants"]] == ["greenwood-code"]
    assert [tenant.slug for tenant in by_code.context["tenants"]] == ["greenwood-code"]


@pytest.mark.django_db
def test_directory_filters_by_tenant_and_subscription_status_and_plan(client):
    active = make_tenant("Active School", "active-school")
    suspended = make_tenant("Suspended School", "suspended-filter", Tenant.Status.SUSPENDED)
    starter = Plan.objects.get(code="starter")
    Subscription.objects.create(
        tenant=active,
        plan=starter,
        status=Subscription.Status.ACTIVE,
        current_period_end=timezone.now() + timezone.timedelta(days=5),
    )
    Subscription.objects.create(
        tenant=suspended,
        plan=Plan.objects.get(code="standard"),
        status=Subscription.Status.SUSPENDED,
    )
    client.force_login(make_superuser())

    by_tenant_status = client.get(reverse("superuser:tenant-directory"), {"status": "suspended"})
    by_subscription = client.get(
        reverse("superuser:tenant-directory"), {"subscription_status": "active", "plan": "starter"}
    )

    assert [tenant.slug for tenant in by_tenant_status.context["tenants"]] == ["suspended-filter"]
    assert [tenant.slug for tenant in by_subscription.context["tenants"]] == ["active-school"]


@pytest.mark.django_db
def test_directory_sorting_and_pagination(client):
    for index in range(12):
        make_tenant(f"Pageable {index:02}", f"pageable-{index:02}")
    client.force_login(make_superuser())
    url = reverse("superuser:tenant-directory")

    first_page = client.get(url, {"q": "Pageable", "sort": "name", "direction": "asc"})
    second_page = client.get(url, {"q": "Pageable", "sort": "name", "direction": "asc", "page": 2})

    assert first_page.context["tenants"][0].name == "Pageable 00"
    assert len(first_page.context["tenants"]) == 10
    assert len(second_page.context["tenants"]) == 2
    assert "q=Pageable&amp;sort=name&amp;direction=asc&amp;page=2" in first_page.content.decode()


@pytest.mark.django_db
def test_drawer_returns_requested_tenant_and_administrator(client, tenant_a, tenant_b, admin_a):
    admin_a.full_name = "Tenant Administrator"
    admin_a.save(update_fields=["full_name"])
    Membership.objects.filter(user=admin_a, tenant=tenant_a).update(role=Role.OWNER)
    client.force_login(make_superuser())

    response = client.get(reverse("superuser:tenant-directory-drawer", args=[tenant_a.pk]))

    assert response.status_code == 200
    assert b"Tenant Administrator" in response.content
    assert admin_a.email.encode() in response.content
    assert tenant_b.name.encode() not in response.content


@pytest.mark.django_db
def test_school_user_cannot_fetch_another_tenants_drawer(client, tenant_b, admin_a):
    client.force_login(admin_a)
    response = client.get(reverse("superuser:tenant-directory-drawer", args=[tenant_b.pk]))
    assert response.status_code == 403


@pytest.mark.django_db
def test_export_requires_superuser_and_respects_directory_filters(client):
    make_tenant("Export Match", "export-match")
    make_tenant("Do Not Export", "do-not-export")
    url = reverse("superuser:tenant-directory-export")
    assert client.get(url).status_code == 302

    client.force_login(make_superuser())
    response = client.get(url, {"q": "Export Match"})
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))

    assert response["Content-Type"].startswith("text/csv")
    assert response["Content-Disposition"].endswith('"kuzenga-tenants.csv"')
    assert len(rows) == 2
    assert rows[1][0] == "Export Match"


@pytest.mark.django_db
def test_export_neutralizes_formula_cells(client):
    make_tenant('=HYPERLINK("https://example.test")', "=formula-school")
    client.force_login(make_superuser())

    response = client.get(reverse("superuser:tenant-directory-export"))
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))

    assert rows[1][0].startswith("'=")
    assert rows[1][1].startswith("'=")


@pytest.mark.django_db
def test_platform_superuser_directory_is_not_scoped_to_active_school(client, tenant_a, tenant_b):
    superuser = make_superuser()
    Membership.objects.create(user=superuser, tenant=tenant_a, role=Role.ADMIN)
    client.force_login(superuser)

    response = client.get(reverse("superuser:tenant-directory"))

    assert {tenant.slug for tenant in response.context["tenants"]} == {tenant_a.slug, tenant_b.slug}


@pytest.mark.django_db
def test_superuser_can_view_tenant_overview_with_tenant_scoped_database_data(
    client, tenant_a, tenant_b, admin_a, teacher_a
):
    admin_a.full_name = "Tenant Owner"
    admin_a.save(update_fields=["full_name"])
    with tenant_context(tenant_a):
        Student.objects.create(admission_number="A-001", first_name="Aro", last_name="One")
        year = AcademicYear.objects.create(
            name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), is_current=True
        )
        grade = Grade.objects.create(name="Form 1", level_order=1)
        ClassGroup.objects.create(academic_year=year, grade=grade, name="1A")
    with tenant_context(tenant_b):
        Student.objects.create(admission_number="B-001", first_name="Bee", last_name="Two")
        Student.objects.create(admission_number="B-002", first_name="Bea", last_name="Three")
    audit.record(
        "tenant.overview_checked", actor=admin_a, obj=tenant_a, tenant=tenant_a
    )
    audit.record("tenant.other_school_event", tenant=tenant_b)
    client.force_login(make_superuser())

    response = client.get(reverse("superuser:tenant-overview", args=[tenant_a.pk]))

    assert response.status_code == 200
    assert tenant_a.name.encode() in response.content
    assert tenant_b.name.encode() not in response.content
    assert b"Tenant Owner" in response.content
    assert b"tenant overview checked" in response.content.lower()
    assert b"other school event" not in response.content.lower()
    assert response.context["metrics"] == {
        "students": 1,
        "teachers": 1,
        "users": 2,
        "classes": 1,
    }
    assert response.context["tenant_status_label"] == "Active"
    assert response.context["active_section"] == "tenant-overview"
    assert response.context["can_suspend"]
    assert not response.context["can_reactivate"]
    assert b'aria-current="page"' in response.content
    assert b"Suspend Tenant" in response.content


@pytest.mark.django_db
def test_tenant_overview_rejects_unauthorised_users(client, tenant_a, admin_a):
    url = reverse("superuser:tenant-overview", args=[tenant_a.pk])
    assert client.get(url).status_code == 302

    client.force_login(admin_a)
    assert client.get(url).status_code == 403


@pytest.mark.django_db
def test_tenant_status_action_suspends_and_restores_previous_status(client, tenant_a):
    tenant_a.status = Tenant.Status.TRIAL
    tenant_a.save(update_fields=["status", "updated_at"])
    client.force_login(make_superuser())
    url = reverse("superuser:tenant-overview-status", args=[tenant_a.pk])

    suspended = client.post(url, {"action": "suspend"})
    tenant_a.refresh_from_db()
    assert suspended.status_code == 302
    assert suspended.url == reverse("superuser:tenant-overview", args=[tenant_a.pk])
    assert tenant_a.status == Tenant.Status.SUSPENDED

    overview = client.get(suspended.url)
    assert overview.context["can_reactivate"]
    assert not overview.context["can_suspend"]
    assert b"Reactivate Tenant" in overview.content

    reactivated = client.post(url, {"action": "reactivate"})
    tenant_a.refresh_from_db()
    assert reactivated.status_code == 302
    assert tenant_a.status == Tenant.Status.TRIAL
    assert AuditEvent.objects.filter(
        tenant=tenant_a, action="tenant.status_changed", metadata__status="suspended"
    ).exists()
    status_event = AuditEvent.objects.filter(
        tenant=tenant_a, action="tenant.status_changed", metadata__status="suspended"
    ).latest("created_at")
    assert status_event.actor.is_superuser
    assert status_event.changes["status"] == {"before": "trial", "after": "suspended"}


@pytest.mark.django_db
def test_tenant_status_action_requires_platform_superuser(client, tenant_a, admin_a):
    url = reverse("superuser:tenant-overview-status", args=[tenant_a.pk])
    assert client.post(url, {"action": "suspend"}).status_code == 302

    client.force_login(admin_a)
    assert client.post(url, {"action": "suspend"}).status_code == 403
    tenant_a.refresh_from_db()
    assert tenant_a.status == Tenant.Status.ACTIVE


@pytest.mark.django_db
def test_directory_name_and_view_details_open_selected_tenant_overview(client, tenant_a):
    client.force_login(make_superuser())

    response = client.get(reverse("superuser:tenant-directory"))
    overview_url = reverse("superuser:tenant-overview", args=[tenant_a.pk])

    assert response.status_code == 200
    assert f'href="{overview_url}"'.encode() in response.content
    assert b"View Details" in response.content
    assert client.get(overview_url).status_code == 200


@pytest.mark.django_db
def test_tenant_overview_quick_actions_resolve_to_existing_destinations(
    client, tenant_a, admin_a, admin_b
):
    client.force_login(make_superuser())
    overview = client.get(reverse("superuser:tenant-overview", args=[tenant_a.pk]))
    subscription = Subscription.objects.filter(tenant=tenant_a).latest("created_at")

    assert overview.status_code == 200
    assert overview.context["edit_tenant_url"] == reverse(
        "admin:tenancy_tenant_change", args=[tenant_a.pk]
    )
    assert overview.context["configure_tenant_url"] == reverse(
        "superuser:tenant-configuration", args=[tenant_a.pk]
    )
    assert client.get(overview.context["configure_tenant_url"]).status_code == 200
    assert overview.context["manage_administrators_url"] == reverse(
        "superuser:tenant-users", args=[tenant_a.pk]
    )
    assert overview.context["manage_subscription_url"] == reverse(
        "superuser:tenant-subscriptions", args=[tenant_a.pk]
    )
    assert overview.context["can_suspend"]
    assert f'href="{overview.context["activity_url"]}"'.encode() in overview.content
    tenant_edit = client.get(overview.context["edit_tenant_url"])
    administrator_list = client.get(overview.context["manage_administrators_url"])
    subscription_edit = client.get(overview.context["manage_subscription_url"])
    assert tenant_edit.status_code == 200
    assert tenant_edit.context["original"].pk == tenant_a.pk
    assert administrator_list.status_code == 200
    assert tenant_a.name.encode() in administrator_list.content
    assert subscription_edit.status_code == 200
    assert subscription in subscription_edit.context["subscriptions"]
