from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, CharField, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from django.utils import timezone

from apps.core import audit
from apps.core.context import tenant_context
from apps.core.models import AuditEvent

from .configuration_services import ensure_tenant_configuration
from .models import Entitlement, Membership, Module, Plan, Role, Subscription, SubscriptionEvent, Tenant

TENANT_DIRECTORY_SORTS = {
    "name": "name",
    "status": "status",
    "registered": "created_at",
    "users": "user_count",
    "administrator": "primary_admin_name",
    "subscription": "latest_period_end",
}


def tenant_directory_queryset(params=None):
    """Build the shared, platform-wide tenant directory query with validated filters."""
    params = params or {}
    admin_memberships = Membership.objects.filter(
        tenant_id=OuterRef("pk"),
        status=Membership.Status.ACTIVE,
        role__in=(Role.OWNER, Role.ADMIN),
        user__is_active=True,
    ).order_by(
        Case(
            When(role=Role.OWNER, then=0),
            default=1,
            output_field=IntegerField(),
        ),
        "created_at",
    )
    latest_subscription = Subscription.objects.filter(tenant_id=OuterRef("pk")).order_by(
        "-created_at", "-pk"
    )

    tenants = Tenant.objects.annotate(
        user_count=Count(
            "memberships__user_id",
            filter=Q(
                memberships__status=Membership.Status.ACTIVE,
                memberships__user__is_active=True,
            ),
            distinct=True,
        ),
        primary_admin_name=Subquery(admin_memberships.values("user__full_name")[:1]),
        primary_admin_email=Subquery(admin_memberships.values("user__email")[:1]),
        latest_plan_name=Subquery(latest_subscription.values("plan__name")[:1]),
        latest_plan_code=Subquery(latest_subscription.values("plan__code")[:1]),
        latest_subscription_status=Subquery(latest_subscription.values("status")[:1]),
        latest_subscription_label=Case(
            *(
                When(latest_subscription_status=value, then=Value(label))
                for value, label in Subscription.Status.choices
            ),
            default=Value(""),
            output_field=CharField(),
        ),
        latest_period_end=Subquery(latest_subscription.values("current_period_end")[:1]),
    )

    search = params.get("q", "").strip()
    if search:
        tenants = tenants.filter(Q(name__icontains=search) | Q(slug__icontains=search))

    status = params.get("status", "")
    if status in Tenant.Status.values:
        tenants = tenants.filter(status=status)

    subscription_status = params.get("subscription_status", "")
    if subscription_status in Subscription.Status.values:
        tenants = tenants.filter(latest_subscription_status=subscription_status)

    plan = params.get("plan", "")
    if plan and Plan.objects.filter(code=plan).exists():
        tenants = tenants.filter(latest_plan_code=plan)

    sort_key = params.get("sort", "registered")
    sort_field = TENANT_DIRECTORY_SORTS.get(sort_key, "created_at")
    direction = "" if params.get("direction") == "asc" else "-"
    return tenants.order_by(f"{direction}{sort_field}", "pk")


def tenant_directory_metrics():
    """Return unfiltered tenant counts and the count with a period ending soon."""
    now = timezone.now()
    return {
        "total_tenants": Tenant.objects.count(),
        "active_tenants": Tenant.objects.filter(status=Tenant.Status.ACTIVE).count(),
        "pending_tenants": Tenant.objects.filter(status=Tenant.Status.TRIAL).count(),
        "suspended_tenants": Tenant.objects.filter(status=Tenant.Status.SUSPENDED).count(),
        "expiring_soon": Tenant.objects.filter(
            status__in=(Tenant.Status.ACTIVE, Tenant.Status.TRIAL),
            subscriptions__status__in=(Subscription.Status.ACTIVE, Subscription.Status.TRIAL),
            subscriptions__current_period_end__gt=now,
            subscriptions__current_period_end__lte=now + timedelta(days=30),
        ).distinct().count(),
    }


@transaction.atomic
def change_tenant_status(tenant, *, action, actor, request=None):
    """Suspend an active/trial tenant or restore its status after a platform suspension."""
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    if action == "suspend":
        if tenant.status not in (Tenant.Status.ACTIVE, Tenant.Status.TRIAL):
            raise ValidationError("Only active or trial tenants can be suspended.")
        previous_status = tenant.status
        next_status = Tenant.Status.SUSPENDED
    elif action == "reactivate":
        if tenant.status != Tenant.Status.SUSPENDED:
            raise ValidationError("Only suspended tenants can be reactivated.")
        previous_event = AuditEvent.objects.filter(
            tenant=tenant, action="tenant.status_changed"
        ).first()
        previous_status = (
            previous_event.metadata.get("previous_status")
            if previous_event and previous_event.metadata.get("status") == Tenant.Status.SUSPENDED
            else Tenant.Status.ACTIVE
        )
        if previous_status not in (Tenant.Status.ACTIVE, Tenant.Status.TRIAL):
            previous_status = Tenant.Status.ACTIVE
        next_status = previous_status
    else:
        raise ValidationError("Choose a valid tenant status action.")

    tenant.status = next_status
    tenant.save(update_fields=["status", "updated_at"])
    audit.record(
        "tenant.status_changed",
        actor=actor,
        obj=tenant,
        tenant=tenant,
        request=request,
        changes={"status": {"before": previous_status, "after": next_status}},
        previous_status=previous_status,
        status=next_status,
    )
    return tenant


def active_module_codes(tenant) -> set[str]:
    return set(
        Entitlement.objects.active().filter(tenant=tenant).values_list("module_id", flat=True)
    )


def has_module(tenant, code: str) -> bool:
    """Central entitlement check. Fails closed."""
    if tenant is None:
        return False
    return Entitlement.objects.active().filter(tenant=tenant, module_id=code).exists()


@transaction.atomic
def activate_plan(
    tenant,
    plan,
    *,
    actor=None,
    period_days=30,
    trial_days=None,
    started_at=None,
    current_period_end=None,
    request=None,
) -> Subscription:
    """Activate a plan and grant its module entitlements. Billing can be manual/offline for MVP."""
    now = timezone.now()
    is_trial = bool(trial_days)
    started_at = started_at or now
    period_end = current_period_end or started_at + timedelta(days=trial_days or period_days)
    if not plan.is_active:
        raise ValidationError("Choose an active plan.")
    sub = Subscription(
        tenant=tenant,
        plan=plan,
        status=Subscription.Status.TRIAL if is_trial else Subscription.Status.ACTIVE,
        started_at=started_at,
        current_period_end=period_end,
        trial_ends_at=period_end if is_trial else None,
    )
    sub.full_clean()
    sub.save()
    source = Entitlement.Source.TRIAL if is_trial else Entitlement.Source.PLAN
    for module in plan.modules.filter(is_active=True):
        Entitlement.objects.create(
            tenant=tenant,
            module=module,
            subscription=sub,
            source=source,
            valid_from=started_at,
            valid_until=period_end,
        )
    SubscriptionEvent.objects.create(
        tenant=tenant,
        subscription=sub,
        event_type="activated",
        actor=actor,
        detail={"plan": plan.code, "trial": is_trial},
    )
    audit.record(
        "subscription.activated",
        actor=actor,
        obj=sub,
        tenant=tenant,
        request=request,
        changes={"plan": {"before": None, "after": plan.code}, "status": {"before": None, "after": sub.status}},
        plan=plan.code,
    )
    return sub


@transaction.atomic
def register_tenant(
    *,
    school,
    administrator,
    password,
    plan,
    tenant_status,
    subscription_start,
    subscription_expiry,
    academic_year_start,
    academic_year_end,
    actor,
    request=None,
):
    """Create a tenant, its initial owner and plan configuration as one transaction."""
    from django.contrib.auth import get_user_model

    from apps.academics.models import AcademicYear

    if not plan.is_active:
        raise ValidationError("The selected subscription plan is no longer available.")

    User = get_user_model()
    tenant = Tenant.objects.create(
        name=school["name"],
        slug=school["code"],
        country=school["country"],
        timezone=school["timezone"],
        default_currency=school["default_currency"],
        status=tenant_status,
    )
    ensure_tenant_configuration(tenant)
    full_name = f"{administrator['first_name']} {administrator['last_name']}".strip()
    user = User.objects.create_user(administrator["email"], password, full_name=full_name)
    Membership.objects.create(user=user, tenant=tenant, role=Role.OWNER)

    starts_at = timezone.make_aware(datetime.combine(subscription_start, time.min))
    expires_at = timezone.make_aware(datetime.combine(subscription_expiry, time.max))
    trial_days = (subscription_expiry - subscription_start).days if tenant_status == Tenant.Status.TRIAL else None
    activate_plan(
        tenant,
        plan,
        actor=actor,
        trial_days=trial_days,
        started_at=starts_at,
        current_period_end=expires_at,
        request=request,
    )
    if tenant_status in (Tenant.Status.SUSPENDED, Tenant.Status.ARCHIVED):
        suspend_tenant_access(
            tenant,
            actor=actor,
            request=request,
            reason=f"Tenant registered with {tenant_status} status",
        )

    with tenant_context(tenant):
        AcademicYear.objects.create(
            name=str(academic_year_start.year),
            start_date=academic_year_start,
            end_date=academic_year_end,
            is_current=True,
        )

    audit.record(
        "tenant.created",
        actor=actor,
        obj=tenant,
        tenant=tenant,
        request=request,
        affected_user=user,
        changes={"status": {"before": None, "after": tenant.status}},
        plan=plan.code,
    )
    return tenant, user


@transaction.atomic
def grant_module(
    tenant, module_code, *, actor, reason, valid_days=30, source=Entitlement.Source.EXCEPTION, request=None
) -> Entitlement:
    """Documented exception/promo access: needs an approver, a reason and an expiry."""
    module = Module.objects.get(code=module_code)
    now = timezone.now()
    ent = Entitlement.objects.create(
        tenant=tenant,
        module=module,
        source=source,
        reason=reason,
        approved_by=actor,
        valid_from=now,
        valid_until=now + timedelta(days=valid_days),
    )
    SubscriptionEvent.objects.create(
        tenant=tenant,
        event_type="module_granted",
        actor=actor,
        detail={"module": module_code, "reason": reason},
    )
    audit.record(
        "entitlement.granted", actor=actor, obj=ent, tenant=tenant, request=request, module=module_code
    )
    return ent


@transaction.atomic
def suspend_tenant_access(tenant, *, actor=None, reason="", request=None) -> None:
    Entitlement.objects.filter(tenant=tenant, status=Entitlement.Status.ACTIVE).update(
        status=Entitlement.Status.REVOKED
    )
    Subscription.objects.filter(tenant=tenant, status__in=["active", "trial", "past_due"]).update(
        status=Subscription.Status.SUSPENDED
    )
    SubscriptionEvent.objects.create(
        tenant=tenant, event_type="suspended", actor=actor, detail={"reason": reason}
    )
    audit.record("subscription.suspended", actor=actor, tenant=tenant, request=request, reason=reason)
