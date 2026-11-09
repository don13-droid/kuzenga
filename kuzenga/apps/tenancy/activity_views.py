from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET

from apps.core.models import AuditEvent

from .models import Tenant
from .views import PLATFORM_NAVIGATION

PAGE_SIZE = 50


def _require_platform_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _date_bound(value, *, end=False):
    parsed = parse_date(value or "")
    if parsed is None:
        return None
    day = parsed + timedelta(days=1) if end else parsed
    return timezone.make_aware(datetime.combine(day, time.min))


def _filtered_events(request, *, tenant=None, user=None):
    queryset = AuditEvent.objects.select_related("actor", "target_user", "tenant")
    if tenant is not None:
        queryset = queryset.filter(tenant=tenant)
    if user is not None:
        queryset = queryset.filter(Q(actor=user) | Q(target_user=user))

    search = request.GET.get("q", "").strip()[:200]
    if search:
        queryset = queryset.filter(
            Q(actor__full_name__icontains=search)
            | Q(actor__email__icontains=search)
            | Q(target_user__full_name__icontains=search)
            | Q(target_user__email__icontains=search)
            | Q(tenant__name__icontains=search)
            | Q(tenant__slug__icontains=search)
            | Q(action__icontains=search)
            | Q(description__icontains=search)
        )

    category = request.GET.get("category", "")
    if category in AuditEvent.Category.values:
        queryset = queryset.filter(category=category)
    action = request.GET.get("action", "")
    if action and len(action) <= 100:
        queryset = queryset.filter(action=action)
    outcome = request.GET.get("outcome", "")
    if outcome in AuditEvent.Outcome.values:
        queryset = queryset.filter(outcome=outcome)

    if tenant is None:
        tenant_id = request.GET.get("tenant", "")
        if tenant_id:
            try:
                queryset = queryset.filter(tenant_id=Tenant._meta.pk.to_python(tenant_id))
            except (ValueError, TypeError):
                queryset = queryset.none()

    start = _date_bound(request.GET.get("date_from"))
    end = _date_bound(request.GET.get("date_to"), end=True)
    if start:
        queryset = queryset.filter(created_at__gte=start)
    if end:
        queryset = queryset.filter(created_at__lt=end)

    return queryset.order_by("-created_at", "-id")


def _event_context(event):
    actor = event.actor
    affected_user = event.target_user
    return {
        "event": event,
        "actor_label": (actor.get_full_name() or actor.email) if actor else "System / unauthenticated",
        "actor_kind": "Platform superuser" if actor and actor.is_superuser else ("School user" if actor else "System / unauthenticated"),
        "affected_label": (
            affected_user.get_full_name() or affected_user.email if affected_user else event.object_type
        ),
        "tenant_label": event.tenant.name if event.tenant else "Platform-wide",
        "detail_url": reverse("superuser:activity-event", args=[event.pk]),
    }


def _activity_list(request, queryset, *, title, scope, tenant=None, user_record=None, overview=False):
    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    rows = [_event_context(event) for event in page_obj.object_list]
    query = request.GET.copy()
    query.pop("page", None)
    actions_queryset = AuditEvent.objects.order_by()
    if tenant is not None:
        actions_queryset = actions_queryset.filter(tenant=tenant)
    if user_record is not None:
        actions_queryset = actions_queryset.filter(
            Q(actor=user_record) | Q(target_user=user_record)
        )
    context = {
        "title": title,
        "scope": scope,
        "tenant": tenant,
        "user_record": user_record,
        "rows": rows,
        "page_obj": page_obj,
        "query_string": query.urlencode(),
        "selected_category": request.GET.get("category", ""),
        "selected_action": request.GET.get("action", ""),
        "selected_outcome": request.GET.get("outcome", ""),
        "selected_tenant": request.GET.get("tenant", ""),
        "search": request.GET.get("q", ""),
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "categories": AuditEvent.Category.choices,
        "outcomes": AuditEvent.Outcome.choices,
        "tenants": Tenant.objects.only("id", "name").order_by("name") if tenant is None else (),
        "actions": actions_queryset.values_list("action", flat=True).distinct().order_by("action"),
        "platform_navigation": PLATFORM_NAVIGATION,
        "active_section": "activity",
    }
    if overview:
        since = timezone.now() - timedelta(days=30)
        recent = AuditEvent.objects.filter(created_at__gte=since)
        total = AuditEvent.objects.count()
        context["metrics"] = {
            "total": total,
            "administrative": recent.filter(
                category__in=(
                    AuditEvent.Category.TENANT,
                    AuditEvent.Category.USER,
                    AuditEvent.Category.CONFIGURATION,
                    AuditEvent.Category.SUBSCRIPTION,
                )
            ).count(),
            "user_management": recent.filter(category=AuditEvent.Category.USER).count(),
            "authentication": recent.filter(category=AuditEvent.Category.AUTHENTICATION).count(),
            "configuration": recent.filter(category=AuditEvent.Category.CONFIGURATION).count(),
            "tenant_status": recent.filter(action="tenant.status_changed").count(),
        }
    return render(request, "superuser/activity/list.html", context)


@login_required(login_url="platform-login")
@require_GET
def activity_overview(request):
    _require_platform_superuser(request)
    return _activity_list(
        request,
        _filtered_events(request),
        title="Tenant Activity & Audit Logs",
        scope="platform",
        overview=True,
    )


@login_required(login_url="platform-login")
@require_GET
def tenant_activity(request, tenant_id):
    _require_platform_superuser(request)
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    return _activity_list(
        request,
        _filtered_events(request, tenant=tenant),
        title="Tenant activity",
        scope="tenant",
        tenant=tenant,
    )


@login_required(login_url="platform-login")
@require_GET
def user_activity(request, user_id):
    _require_platform_superuser(request)
    user_record = get_object_or_404(get_user_model(), pk=user_id)
    return _activity_list(
        request,
        _filtered_events(request, user=user_record),
        title="User activity",
        scope="user",
        user_record=user_record,
    )


@login_required(login_url="platform-login")
@require_GET
def activity_event_detail(request, event_id):
    _require_platform_superuser(request)
    event = get_object_or_404(
        AuditEvent.objects.select_related("actor", "target_user", "tenant"), pk=event_id
    )
    context = _event_context(event)
    context.update(
        {
            "platform_navigation": PLATFORM_NAVIGATION,
            "active_section": "activity",
            "tenant_activity_url": (
                reverse("superuser:tenant-activity", args=[event.tenant_id])
                if event.tenant_id
                else None
            ),
            "user_activity_url": (
                reverse("superuser:user-activity", args=[event.target_user_id])
                if event.target_user_id
                else None
            ),
            "actor_activity_url": (
                reverse("superuser:user-activity", args=[event.actor_id]) if event.actor_id else None
            ),
        }
    )
    return render(request, "superuser/activity/detail.html", context)
