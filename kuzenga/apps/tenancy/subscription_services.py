"""Manual platform administration of existing subscriptions (no billing automation)."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.core import audit

from .models import Entitlement, Plan, Subscription, SubscriptionEvent, Tenant


@transaction.atomic
def save_subscription(*, tenant, actor, plan, status, started_at, current_period_end,
                      trial_ends_at=None, subscription_id=None, reason, request=None):
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied
    if not reason.strip():
        raise ValidationError("Enter a reason for this change.")
    # Serialize administration for one tenant, including creation of its first record.
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    plan = Plan.objects.get(pk=plan.pk)
    if not plan.is_active:
        raise ValidationError("Choose an active plan.")
    sub = (
        Subscription.objects.select_for_update().get(pk=subscription_id, tenant=tenant)
        if subscription_id else Subscription(tenant=tenant)
    )
    fields = ("plan_id", "status", "started_at", "current_period_end", "trial_ends_at")
    previous = {field: getattr(sub, field) for field in fields} if subscription_id else {}
    sub.plan = plan
    sub.status = status
    sub.started_at = started_at
    sub.current_period_end = current_period_end
    sub.trial_ends_at = trial_ends_at
    sub.full_clean()
    modules = list(plan.modules.filter(is_active=True).prefetch_related("depends_on"))
    codes = {module.code for module in modules}
    for module in modules:
        if any(dependency.code not in codes for dependency in module.depends_on.all()):
            raise ValidationError("The plan is missing an active module dependency. Update its catalogue first.")
    changes = {
        field: {"before": previous.get(field), "after": getattr(sub, field)}
        for field in fields if previous.get(field) != getattr(sub, field)
    }
    # Only this record's plan grants are replaced. Independently approved grants survive.
    grants = Entitlement.objects.filter(
        tenant=tenant, subscription=sub, source__in=(Entitlement.Source.PLAN, Entitlement.Source.TRIAL)
    ) if subscription_id else Entitlement.objects.none()
    source = Entitlement.Source.TRIAL if sub.status == Subscription.Status.TRIAL else Entitlement.Source.PLAN
    end = sub.trial_ends_at if sub.status == Subscription.Status.TRIAL else sub.current_period_end
    expected = {
        (module.pk, source, sub.started_at, end) for module in modules
    } if sub.status in (Subscription.Status.ACTIVE, Subscription.Status.TRIAL) else set()
    current = list(grants.filter(status=Entitlement.Status.ACTIVE).values_list(
        "module_id", "source", "valid_from", "valid_until"
    ))
    if subscription_id and not changes and len(current) == len(expected) and set(current) == expected:
        return sub
    sub.save()
    grants.filter(status=Entitlement.Status.ACTIVE).update(status=Entitlement.Status.REVOKED)
    if sub.status in (Subscription.Status.ACTIVE, Subscription.Status.TRIAL):
        for module in modules:
            Entitlement.objects.create(
                tenant=tenant, subscription=sub, module=module,
                source=source,
                valid_from=sub.started_at, valid_until=end,
            )
    event_type = "reconciled" if subscription_id and not changes else "updated" if subscription_id else "created"
    SubscriptionEvent.objects.create(
        tenant=tenant, subscription=sub, actor=actor,
        event_type=event_type,
        detail={"reason": reason.strip(), "plan": plan.code, "status": sub.status},
    )
    audit.record(
        f"subscription.{event_type}",
        actor=actor, tenant=tenant, obj=sub, request=request, changes=changes,
        reason=reason.strip(),
    )
    return sub

