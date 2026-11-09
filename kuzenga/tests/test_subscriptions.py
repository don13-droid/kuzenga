from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.tenancy.models import Entitlement, Plan, Subscription, SubscriptionEvent
from apps.tenancy.services import activate_plan, has_module
from apps.tenancy.subscription_services import save_subscription

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator():
    return get_user_model().objects.create_superuser("subscriptions@example.test", "unused-password")


def values(**overrides):
    start = timezone.now().replace(second=0, microsecond=0)
    result = dict(
        plan=Plan.objects.get(code="standard"), status="active", started_at=start,
        current_period_end=start + timedelta(days=30), trial_ends_at=None,
        reason="Manual plan administration",
    )
    result.update(overrides)
    return result


def payload(**overrides):
    data = values(**overrides)
    data["plan"] = data["plan"].pk
    return {key: value.isoformat() if hasattr(value, "isoformat") else value or "" for key, value in data.items()}


def url(tenant, sub=None):
    if sub:
        return reverse("superuser:tenant-subscription-edit", args=[tenant.pk, sub.pk])
    return reverse("superuser:tenant-subscriptions", args=[tenant.pk])


def test_platform_workspace_create_and_audit(client, tenant_a, tenant_b, operator):
    client.force_login(operator)
    response = client.get(url(tenant_a))
    assert response.status_code == 200
    assert tenant_b.name.encode() not in response.content
    assert b'for="id_plan"' in response.content
    assert b'csrfmiddlewaretoken' in response.content
    response = client.post(url(tenant_a), payload())
    assert response.status_code == 302
    sub = tenant_a.subscriptions.latest("created_at")
    assert sub.status == "active"
    assert Entitlement.objects.filter(subscription=sub, tenant=tenant_a).count() == 4
    assert SubscriptionEvent.objects.get(subscription=sub).actor == operator
    event = AuditEvent.objects.get(action="subscription.created", object_id=str(sub.pk))
    assert event.tenant == tenant_a and event.actor == operator
    assert event.changes["status"]["after"] == "active"


def test_update_downgrade_revokes_old_plan_only(tenant_a, tenant_b, operator):
    sub = tenant_a.subscriptions.latest("created_at")
    other_ids = list(tenant_b.entitlements.values_list("pk", "status"))
    exception = Entitlement.objects.create(tenant=tenant_a, module_id="finance", source="exception")
    save_subscription(tenant=tenant_a, actor=operator, subscription_id=sub.pk,
                      **values(plan=Plan.objects.get(code="starter")))
    assert has_module(tenant_a, "students")
    assert not has_module(tenant_a, "attendance")
    assert has_module(tenant_a, "finance")
    exception.refresh_from_db()
    assert exception.status == "active"
    assert list(tenant_b.entitlements.values_list("pk", "status")) == other_ids


@pytest.mark.parametrize("status", ["draft", "pending_payment", "past_due", "suspended", "cancelled", "expired"])
def test_non_access_status_revokes_this_subscription(tenant_a, operator, status):
    sub = tenant_a.subscriptions.latest("created_at")
    save_subscription(tenant=tenant_a, actor=operator, subscription_id=sub.pk, **values(status=status))
    assert not has_module(tenant_a, "students")
    assert tenant_a.subscriptions.get(pk=sub.pk).status == status


def test_trial_and_future_start(tenant_a, operator):
    start = timezone.now() + timedelta(days=2)
    sub = tenant_a.subscriptions.latest("created_at")
    end = start + timedelta(days=7)
    save_subscription(tenant=tenant_a, actor=operator, subscription_id=sub.pk,
                      **values(status="trial", started_at=start, current_period_end=end, trial_ends_at=end))
    assert not has_module(tenant_a, "students")
    assert tenant_a.entitlements.filter(subscription=sub, status="active", source="trial", valid_until=end).count() == 4


@pytest.mark.parametrize("overrides", [
    {"reason": " "}, {"status": "unknown"}, {"started_at": None}, {"current_period_end": None},
    {"current_period_end": timezone.now() - timedelta(days=1)}, {"status": "trial"},
])
def test_invalid_changes_are_atomic(tenant_a, operator, overrides):
    sub = tenant_a.subscriptions.latest("created_at")
    count = SubscriptionEvent.objects.count()
    with pytest.raises(ValidationError):
        save_subscription(tenant=tenant_a, actor=operator, subscription_id=sub.pk, **values(**overrides))
    sub.refresh_from_db()
    assert sub.status == "active"
    assert has_module(tenant_a, "students")
    assert SubscriptionEvent.objects.count() == count


def test_school_and_anonymous_denied(client, tenant_a, tenant_b, admin_a):
    assert client.get(url(tenant_a)).url.startswith("/platform/login/")
    client.force_login(admin_a)
    for tenant in (tenant_a, tenant_b):
        assert client.get(url(tenant)).status_code == 403
        assert client.post(url(tenant), payload()).status_code == 403
    with pytest.raises(PermissionDenied):
        save_subscription(tenant=tenant_a, actor=admin_a, **values())


def test_cross_tenant_record_denied(client, tenant_a, tenant_b, operator):
    client.force_login(operator)
    sub = tenant_b.subscriptions.latest("created_at")
    assert client.get(url(tenant_a, sub)).status_code == 404
    assert client.post(url(tenant_a, sub), payload()).status_code == 404
    with pytest.raises(Subscription.DoesNotExist):
        save_subscription(tenant=tenant_a, actor=operator, subscription_id=sub.pk, **values())


def test_csrf_invalid_form_and_methods(client, tenant_a, operator):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(operator)
    assert csrf_client.post(url(tenant_a), payload()).status_code == 403
    client.force_login(operator)
    assert client.put(url(tenant_a)).status_code == 405
    response = client.post(url(tenant_a), payload(status="trial"))
    assert response.status_code == 400
    assert "trial_ends_at" in response.context["form"].errors


def test_django_admin_cannot_bypass_subscription_service(client, tenant_a, operator):
    client.force_login(operator)
    sub = tenant_a.subscriptions.latest("created_at")
    change_url = reverse("admin:tenancy_subscription_change", args=[sub.pk])
    assert client.get(change_url).status_code == 200
    assert client.post(change_url, {"status": "suspended"}).status_code == 403
    assert client.post(reverse("admin:tenancy_subscription_add"), payload()).status_code == 403
    assert client.post(reverse("admin:tenancy_subscription_delete", args=[sub.pk]), {"post": "yes"}).status_code == 403
    sub.refresh_from_db()
    assert sub.status == "active" and has_module(tenant_a, "students")


def test_inactive_plan_and_missing_dependency(tenant_a, operator):
    plan = Plan.objects.get(code="standard")
    plan.is_active = False
    plan.save()
    with pytest.raises(ValidationError):
        save_subscription(tenant=tenant_a, actor=operator, **values(plan=plan))
    plan.is_active = True
    plan.save()
    plan.modules.remove("academics")
    with pytest.raises(ValidationError):
        save_subscription(tenant=tenant_a, actor=operator, **values(plan=plan))


def test_repeated_unchanged_edit_is_noop(tenant_a, operator):
    sub = tenant_a.subscriptions.latest("created_at")
    data = values(started_at=sub.started_at, current_period_end=sub.current_period_end)
    before = (SubscriptionEvent.objects.count(), Entitlement.objects.count(), AuditEvent.objects.count())
    save_subscription(tenant=tenant_a, actor=operator, subscription_id=sub.pk, **data)
    assert before == (SubscriptionEvent.objects.count(), Entitlement.objects.count(), AuditEvent.objects.count())


def test_entitlement_rejects_other_tenant_subscription(tenant_a, tenant_b):
    ent = Entitlement(tenant=tenant_a, module_id="students", subscription=tenant_b.subscriptions.first())
    with pytest.raises(ValidationError):
        ent.full_clean()
    with pytest.raises(ValidationError):
        ent.save()


def test_history_is_immutable_and_rejects_cross_tenant_links(tenant_a, tenant_b):
    event = tenant_a.subscription_events.first()
    with pytest.raises(RuntimeError):
        event.save()
    with pytest.raises(RuntimeError):
        event.delete()
    with pytest.raises(RuntimeError):
        SubscriptionEvent.objects.filter(pk=event.pk).update(event_type="changed")
    with pytest.raises(RuntimeError):
        SubscriptionEvent.objects.filter(pk=event.pk).delete()
    with pytest.raises(ValidationError):
        SubscriptionEvent.objects.create(tenant=tenant_b, subscription=event.subscription, event_type="invalid")


def test_activation_respects_future_dates_and_rejects_inverted_period(tenant_a):
    start = timezone.now() + timedelta(days=2)
    plan = Plan.objects.get(code="standard")
    sub = activate_plan(tenant_a, plan, started_at=start)
    assert not Entitlement.objects.active().filter(subscription=sub).exists()
    with pytest.raises(ValidationError):
        activate_plan(tenant_a, plan, started_at=start, current_period_end=start)


def test_audit_failure_rolls_back_subscription_and_entitlements(tenant_a, operator, monkeypatch):
    sub = tenant_a.subscriptions.latest("created_at")
    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")
    monkeypatch.setattr("apps.tenancy.subscription_services.audit.record", fail)
    with pytest.raises(RuntimeError):
        save_subscription(tenant=tenant_a, actor=operator, subscription_id=sub.pk, **values(status="suspended"))
    sub.refresh_from_db()
    assert sub.status == "active" and has_module(tenant_a, "students")
