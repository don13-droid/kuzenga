from types import SimpleNamespace

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts.admin import UserAdmin
from apps.accounts.models import User
from apps.core import audit
from apps.core.admin import AuditEventAdmin
from apps.core.models import AuditEvent
from apps.tenancy.models import Membership


def make_platform_user():
    return User.objects.create_superuser("audit-platform@example.test", "Unused-password-1!")


@pytest.mark.django_db
def test_audit_service_records_actor_target_tenant_request_and_redacted_changes(tenant_a, admin_a):
    request = RequestFactory().post("/account/password-reset/secret-token/")
    request.META["REMOTE_ADDR"] = "192.0.2.18"
    request.META["HTTP_USER_AGENT"] = "Kuzenga audit test agent"
    request.resolver_match = SimpleNamespace(view_name="test:user-edit")

    event = audit.record(
        "tenant.user_updated",
        actor=admin_a,
        obj=Membership.objects.get(user=admin_a, tenant=tenant_a),
        tenant=tenant_a,
        request=request,
        changes={
            "role": {"before": "teacher", "after": "admin"},
            "email": {"before": "private@example.test", "after": "new@example.test"},
            "password": "Never persist this",
        },
        reset_token="Never persist this either",
    )

    assert event.actor == admin_a
    assert event.target_user == admin_a
    assert event.tenant == tenant_a
    assert event.category == AuditEvent.Category.USER
    assert event.ip_address == "192.0.2.18"
    assert event.user_agent == "Kuzenga audit test agent"
    assert event.request_route == "test:user-edit"
    assert event.changes["role"] == {"before": "teacher", "after": "admin"}
    assert event.changes["email"] == "[REDACTED]"
    assert event.changes["password"] == "[REDACTED]"
    assert event.metadata["reset_token"] == "[REDACTED]"
    assert "secret-token" not in str(event.metadata) + str(event.changes)


@pytest.mark.django_db
def test_audit_events_cannot_be_updated_or_deleted_through_orm(tenant_a, admin_a):
    event = audit.record("test.append_only", actor=admin_a, tenant=tenant_a)

    with pytest.raises(RuntimeError):
        event.save()
    with pytest.raises(RuntimeError):
        event.delete()
    with pytest.raises(RuntimeError):
        AuditEvent.objects.filter(pk=event.pk).update(action="rewritten")
    with pytest.raises(RuntimeError):
        AuditEvent.objects.filter(pk=event.pk).delete()


@pytest.mark.django_db
def test_login_failure_success_and_logout_are_recorded_without_credentials(client, admin_a):
    failed = client.post(
        reverse("login"), {"username": admin_a.email, "password": "Wrong-Secret-123!"}
    )
    failure = AuditEvent.objects.get(action="authentication.login_failed")
    assert failed.status_code == 200
    assert failure.target_user == admin_a
    assert failure.actor is None
    assert failure.outcome == AuditEvent.Outcome.FAILURE
    assert "Wrong-Secret-123!" not in str(failure.metadata) + str(failure.changes)

    success = client.post(
        reverse("login"), {"username": admin_a.email, "password": "pass12345!"}
    )
    login_event = AuditEvent.objects.filter(action="authentication.login_succeeded").latest(
        "created_at"
    )
    assert success.status_code == 302
    assert login_event.actor == admin_a
    assert login_event.target_user == admin_a
    assert login_event.tenant_id == Membership.objects.get(user=admin_a).tenant_id

    client.post(reverse("logout"))
    assert AuditEvent.objects.filter(action="authentication.logout", actor=admin_a).exists()


@pytest.mark.django_db
def test_wrong_portal_attempt_is_logged_once(client):
    platform_user = make_platform_user()
    response = client.post(
        reverse("login"),
        {"username": platform_user.email, "password": "Unused-password-1!"},
    )

    assert response.status_code == 200
    failure = AuditEvent.objects.get(action="authentication.login_failed")
    assert failure.target_user == platform_user
    assert failure.category == AuditEvent.Category.AUTHENTICATION
    assert failure.outcome == AuditEvent.Outcome.FAILURE


@pytest.mark.django_db
def test_activity_views_are_platform_only_and_tenant_scoped(
    client, tenant_a, tenant_b, admin_a, admin_b
):
    platform_user = make_platform_user()
    audit.record("tenant.status_changed", actor=platform_user, tenant=tenant_a)
    audit.record("tenant.status_changed", actor=platform_user, tenant=tenant_b)
    global_url = reverse("superuser:activity-overview")
    tenant_url = reverse("superuser:tenant-activity", args=[tenant_a.pk])

    assert client.get(global_url).url.startswith(reverse("platform-login"))
    client.force_login(admin_a)
    assert client.get(global_url).status_code == 403
    assert client.get(tenant_url).status_code == 403

    client.force_login(platform_user)
    response = client.get(tenant_url)
    assert response.status_code == 200
    assert tenant_a.name.encode() in response.content
    assert tenant_b.name.encode() not in response.content
    assert admin_a.email.encode() in response.content
    assert admin_b.email.encode() not in response.content


@pytest.mark.django_db
def test_activity_search_filters_date_outcome_and_paginates(client, tenant_a, admin_a):
    for index in range(55):
        audit.record(
            "tenant.audit_search_test",
            actor=admin_a,
            tenant=tenant_a,
            description=f"Searchable audit action {index}",
        )
    audit.record(
        "authentication.login_failed",
        tenant=tenant_a,
        outcome=AuditEvent.Outcome.FAILURE,
        description="Unrelated failed login",
    )
    client.force_login(make_platform_user())
    url = reverse("superuser:tenant-activity", args=[tenant_a.pk])
    today = timezone.localdate().isoformat()

    first = client.get(url, {"q": "Searchable", "date_from": today, "date_to": today})
    second = client.get(
        url,
        {"q": "Searchable", "date_from": today, "date_to": today, "page": "2"},
    )
    failed_only = client.get(url, {"outcome": "failure", "action": "authentication.login_failed"})

    assert first.status_code == 200
    assert first.context["page_obj"].paginator.count == 55
    assert len(first.context["rows"]) == 50
    assert second.context["page_obj"].number == 2
    assert len(second.context["rows"]) == 5
    assert failed_only.context["page_obj"].paginator.count == 1
    by_category = client.get(url, {"category": AuditEvent.Category.TENANT, "action": "tenant.audit_search_test"})
    assert by_category.context["page_obj"].paginator.count == 55


@pytest.mark.django_db
def test_user_activity_shows_actor_and_affected_user_events(client, tenant_a, admin_a):
    audit.record("tenant.user_updated", actor=admin_a, obj=Membership.objects.get(user=admin_a), tenant=tenant_a)
    client.force_login(make_platform_user())

    response = client.get(reverse("superuser:user-activity", args=[admin_a.pk]))

    assert response.status_code == 200
    assert admin_a.email.encode() in response.content
    assert response.context["user_record"] == admin_a


@pytest.mark.django_db
def test_audit_event_detail_is_read_only_and_shows_safe_changes(client, tenant_a, admin_a):
    event = audit.record(
        "tenant.user_updated",
        actor=admin_a,
        obj=Membership.objects.get(user=admin_a),
        tenant=tenant_a,
        changes={"role": {"before": "teacher", "after": "admin"}, "password": "secret"},
    )
    client.force_login(make_platform_user())

    response = client.get(reverse("superuser:activity-event", args=[event.pk]))

    assert response.status_code == 200
    assert b"teacher" in response.content and b"admin" in response.content
    assert b"secret" not in response.content
    assert b"Audit events are append-only" in response.content


@pytest.mark.django_db
def test_user_admin_disables_permanent_account_deletion():
    request = RequestFactory().get("/admin/accounts/user/")
    admin = UserAdmin(User, AdminSite())

    assert not admin.has_delete_permission(request)


@pytest.mark.django_db
def test_platform_admin_password_reset_is_audited_without_password_values(client, admin_a):
    platform_user = make_platform_user()
    client.force_login(platform_user)
    url = reverse("admin:auth_user_password_change", args=[admin_a.pk])

    response = client.post(
        url,
        {"password1": "Admin-Reset-Password-831!", "password2": "Admin-Reset-Password-831!"},
    )

    event = AuditEvent.objects.get(action="user.password_reset_completed", target_user=admin_a)
    assert response.status_code == 302
    assert event.actor == platform_user
    assert event.tenant_id == Membership.objects.get(user=admin_a).tenant_id
    assert "Admin-Reset-Password-831!" not in str(event.metadata) + str(event.changes)


@pytest.mark.django_db
def test_audit_admin_is_read_only():
    request = RequestFactory().get("/admin/core/auditevent/")
    admin = AuditEventAdmin(AuditEvent, AdminSite())

    assert not admin.has_add_permission(request)
    assert not admin.has_change_permission(request)
    assert not admin.has_delete_permission(request)
