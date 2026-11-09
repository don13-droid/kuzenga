from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .models import Subscription, Tenant
from .subscription_forms import SubscriptionForm
from .subscription_services import save_subscription
from .views import PLATFORM_NAVIGATION


@login_required(login_url="platform-login")
@require_http_methods(["GET", "POST"])
def tenant_subscriptions(request, tenant_id, subscription_id=None):
    if not request.user.is_superuser:
        raise PermissionDenied
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    subscription = (
        get_object_or_404(Subscription, tenant=tenant, pk=subscription_id)
        if subscription_id else Subscription(tenant=tenant)
    )
    form = SubscriptionForm(request.POST if request.method == "POST" else None, instance=subscription)
    if request.method == "POST" and form.is_valid():
        try:
            save_subscription(
                tenant=tenant, actor=request.user, subscription_id=subscription_id,
                request=request, **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Subscription saved and plan access synchronized.")
            return redirect("superuser:tenant-subscriptions", tenant_id=tenant.pk)
    records = tenant.subscriptions.select_related("plan").order_by("-created_at", "-pk")
    history = tenant.subscription_events.select_related("actor", "subscription__plan")
    return render(request, "superuser/subscriptions/manage.html", {
        "tenant": tenant, "form": form, "editing": subscription_id is not None,
        "subscriptions": Paginator(records, 20).get_page(request.GET.get("page")),
        "history": Paginator(history, 20).get_page(request.GET.get("history_page")),
        "entitlements": tenant.entitlements.active().select_related("module").order_by("module__name"),
        "platform_navigation": PLATFORM_NAVIGATION, "active_section": "tenant-overview",
    }, status=400 if request.method == "POST" and form.errors else 200)
