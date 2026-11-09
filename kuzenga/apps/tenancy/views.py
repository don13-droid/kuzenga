import csv
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Case, IntegerField, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.models import AuditEvent

from .forms import (
    REGISTRATION_STEPS,
    AdministratorDetailsForm,
    InitialAdministratorPasswordForm,
    SchoolInformationForm,
    SubscriptionConfigurationForm,
)
from .middleware import SESSION_KEY
from .models import Membership, Plan, Role, Subscription, Tenant
from .services import (
    change_tenant_status,
    register_tenant,
    tenant_directory_metrics,
    tenant_directory_queryset,
)

REGISTRATION_SESSION_KEY = "tenant_registration_wizard"

PLATFORM_NAVIGATION = [
    ("Users", "U"),
    ("System Management", "S"),
    ("Plans & Subscriptions", "P"),
    ("Analytics & Reports", "A"),
    ("Audit Logs", "L"),
    ("Integrations", "I"),
    ("Notifications", "N"),
    ("Settings", "S"),
    ("Help & Support", "?"),
]


@login_required
def select_tenant(request):
    memberships = Membership.objects.select_related("tenant").filter(
        user=request.user,
        status=Membership.Status.ACTIVE,
        tenant__status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE],
    )
    if request.method == "POST":
        chosen = memberships.filter(tenant_id=request.POST.get("tenant")).first()
        if chosen:
            request.session[SESSION_KEY] = str(chosen.tenant_id)
            return redirect("dashboard")
    return render(request, "tenancy/select.html", {"memberships": memberships})


def _require_platform_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


@login_required(login_url="platform-login")
@require_GET
def tenant_directory(request):
    _require_platform_superuser(request)
    tenants = tenant_directory_queryset(request.GET)
    paginator = Paginator(tenants, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "superuser/tenants/list.html",
        {
            "tenants": page_obj.object_list,
            "page_obj": page_obj,
            "metrics": tenant_directory_metrics(),
            "plans": Plan.objects.filter(is_active=True).order_by("name"),
            "tenant_statuses": Tenant.Status.choices,
            "subscription_statuses": Subscription.Status.choices,
            "has_filters": any(
                request.GET.get(key) for key in ("q", "status", "subscription_status", "plan")
            ),
            "platform_navigation": PLATFORM_NAVIGATION,
            "active_section": "tenants",
            "messages": messages.get_messages(request),
        },
    )


@login_required(login_url="platform-login")
@require_GET
def tenant_directory_drawer(request, tenant_id):
    _require_platform_superuser(request)
    tenant = get_object_or_404(tenant_directory_queryset(), pk=tenant_id)
    return render(request, "superuser/tenants/_drawer.html", {"tenant": tenant})


@login_required(login_url="platform-login")
@require_GET
def tenant_overview(request, tenant_id):
    _require_platform_superuser(request)
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    now = timezone.now()
    subscription = (
        Subscription.objects.filter(tenant=tenant)
        .select_related("plan")
        .order_by("-created_at", "-pk")
        .first()
    )
    active_memberships = Membership.objects.filter(
        tenant=tenant,
        status=Membership.Status.ACTIVE,
        user__is_active=True,
    )
    active_users = Membership.objects.filter(tenant=tenant, user__is_active=True)
    primary_admin = (
        active_memberships.filter(role__in=(Role.OWNER, Role.ADMIN))
        .select_related("user")
        .order_by(
            Case(
                When(role=Role.OWNER, then=0),
                default=1,
                output_field=IntegerField(),
            ),
            "created_at",
        )
        .first()
    )
    status_label = dict(Tenant.Status.choices).get(tenant.status, tenant.status.title())
    if tenant.status == Tenant.Status.SUSPENDED:
        status_label = "Suspended"
    elif tenant.status == Tenant.Status.ARCHIVED:
        status_label = "Archived"
    elif subscription and (
        subscription.status == Subscription.Status.EXPIRED
        or (subscription.current_period_end and subscription.current_period_end <= now)
    ):
        status_label = "Expired"
    elif tenant.status == Tenant.Status.TRIAL:
        status_label = "Pending"

    status_changes = AuditEvent.objects.filter(
        tenant=tenant,
        action__in=("tenant.status_changed", "tenant.suspended", "tenant.reactivated"),
    ).select_related("actor")
    last_status_change = status_changes.first()

    events = list(
        AuditEvent.objects.filter(tenant=tenant)
        .select_related("actor", "target_user")
        .order_by("-created_at")[:10]
    )
    activity = []
    for event in events:
        action = event.action
        actor = event.actor
        activity.append(
            {
                "action": action.replace(".", " ").replace("_", " ").capitalize(),
                "created_at": event.created_at,
                "actor": (actor.get_full_name() or actor.email) if actor else "System",
            }
        )

    from apps.academics.models import ClassGroup
    from apps.students.models import Student

    metrics = {
        "students": Student.unscoped.filter(tenant=tenant).count(),
        "teachers": active_users.filter(role=Role.TEACHER).values("user_id").distinct().count(),
        "users": active_users.values("user_id").distinct().count(),
        "classes": ClassGroup.unscoped.filter(
            tenant=tenant, academic_year__is_current=True
        ).count(),
    }
    tenant_admin_url = reverse("admin:tenancy_tenant_change", args=[tenant.pk])
    tenant_configuration_url = reverse("superuser:tenant-configuration", args=[tenant.pk])
    return render(
        request,
        "superuser/tenants/overview.html",
        {
            "tenant": tenant,
            "tenant_status_label": status_label,
            "primary_admin": primary_admin,
            "subscription": subscription,
            "metrics": metrics,
            "last_status_change": last_status_change,
            "activity": activity,
            "activity_url": reverse("superuser:tenant-activity", args=[tenant.pk]),
            "edit_tenant_url": tenant_admin_url,
            "configure_tenant_url": tenant_configuration_url,
            "manage_administrators_url": reverse("superuser:tenant-users", args=[tenant.pk]),
            "manage_subscription_url": reverse("superuser:tenant-subscriptions", args=[tenant.pk]),
            "can_suspend": tenant.status in (Tenant.Status.ACTIVE, Tenant.Status.TRIAL),
            "can_reactivate": tenant.status == Tenant.Status.SUSPENDED,
            "platform_navigation": PLATFORM_NAVIGATION,
            "active_section": "tenant-overview",
        },
    )


@login_required(login_url="platform-login")
@require_POST
def tenant_overview_status(request, tenant_id):
    _require_platform_superuser(request)
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    action = request.POST.get("action")
    try:
        change_tenant_status(tenant, action=action, actor=request.user, request=request)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        label = "reactivated" if action == "reactivate" else "suspended"
        messages.success(request, f"{tenant.name} was {label}.")
    return redirect("superuser:tenant-overview", tenant_id=tenant.pk)


def _safe_csv_cell(value):
    value = "" if value is None else str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


@login_required(login_url="platform-login")
@require_GET
def tenant_directory_export(request):
    _require_platform_superuser(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="kuzenga-tenants.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "School",
            "Identifier",
            "Location",
            "Primary administrator",
            "Administrator email",
            "Users",
            "Plan",
            "Subscription status",
            "Tenant status",
            "Registered",
        ]
    )
    for tenant in tenant_directory_queryset(request.GET).iterator(chunk_size=500):
        writer.writerow(
            [
                _safe_csv_cell(tenant.name),
                _safe_csv_cell(tenant.slug),
                _safe_csv_cell(tenant.country),
                _safe_csv_cell(tenant.primary_admin_name or tenant.primary_admin_email),
                _safe_csv_cell(tenant.primary_admin_email),
                tenant.user_count,
                _safe_csv_cell(tenant.latest_plan_name),
                _safe_csv_cell(tenant.latest_subscription_label),
                _safe_csv_cell(tenant.get_status_display()),
                tenant.created_at.isoformat(),
            ]
        )
    return response


def _registration_form(step, request, data, *, bound=False):
    step_data = data.get(str(step), {})
    if step == 1:
        form_class = SchoolInformationForm
        return form_class(request.POST if bound else None, initial=step_data if not bound else None)
    if step == 2:
        form_class = AdministratorDetailsForm
        return form_class(request.POST if bound else None, initial=step_data if not bound else None)
    if step == 3:
        initial = dict(step_data)
        if initial.get("plan"):
            initial["plan"] = Plan.objects.filter(code=initial["plan"]).values_list("pk", flat=True).first()
        today = timezone.localdate()
        initial.setdefault("subscription_start", today.isoformat())
        initial.setdefault("subscription_expiry", (today + timedelta(days=30)).isoformat())
        initial.setdefault("tenant_status", Tenant.Status.ACTIVE)
        return SubscriptionConfigurationForm(
            request.POST if bound else None,
            initial=initial if not bound else None,
        )
    raise ValueError("The review step does not use a configuration form.")


def _registration_context(request, step, form, wizard_data, *, password_form=None, form_status=200):
    review_data = None
    if step == 4:
        config = wizard_data["3"]
        review_data = {
            "school": wizard_data["1"],
            "administrator": wizard_data["2"],
            "configuration": config,
            "plan": Plan.objects.get(code=config["plan"]),
        }
    return render(
        request,
        "superuser/tenants/register.html",
        {
            "step": step,
            "steps": REGISTRATION_STEPS,
            "step_label": REGISTRATION_STEPS[step - 1][1],
            "form": form,
            "password_form": password_form,
            "wizard_data": wizard_data,
            "review_data": review_data,
            "platform_navigation": PLATFORM_NAVIGATION,
            "active_section": "tenants",
            "form_status": form_status,
        },
        status=form_status,
    )


@login_required(login_url="platform-login")
@require_http_methods(["GET", "POST"])
def tenant_registration(request):
    _require_platform_superuser(request)
    wizard_data = request.session.get(REGISTRATION_SESSION_KEY, {})
    try:
        step = int(request.GET.get("step", request.POST.get("step", "1")))
    except (TypeError, ValueError):
        step = 1
    if not 1 <= step <= 4:
        step = 1

    if request.method == "POST" and request.POST.get("action") == "cancel":
        request.session.pop(REGISTRATION_SESSION_KEY, None)
        return redirect("superuser:tenant-directory")

    required_sections = {2: ("1",), 3: ("1", "2"), 4: ("1", "2", "3")}
    missing = next(
        (section for section in required_sections.get(step, ()) if section not in wizard_data),
        None,
    )
    if missing:
        return redirect(f"{reverse('superuser:tenant-register')}?step={int(missing)}")

    if step < 4:
        form = _registration_form(step, request, wizard_data, bound=request.method == "POST")
        if request.method == "POST" and form.is_valid():
            cleaned = form.cleaned_data
            if step == 3:
                cleaned = {
                    **cleaned,
                    "plan": cleaned["plan"].code,
                    "subscription_start": cleaned["subscription_start"].isoformat(),
                    "subscription_expiry": cleaned["subscription_expiry"].isoformat(),
                    "academic_year_start": cleaned["academic_year_start"].isoformat(),
                    "academic_year_end": cleaned["academic_year_end"].isoformat(),
                }
            wizard_data[str(step)] = cleaned
            request.session[REGISTRATION_SESSION_KEY] = wizard_data
            return redirect(f"{reverse('superuser:tenant-register')}?step={step + 1}")
        return _registration_context(request, step, form, wizard_data)

    config = wizard_data["3"]
    plan = Plan.objects.filter(code=config["plan"], is_active=True).first()
    if plan is None:
        messages.error(request, "That subscription plan is no longer available. Choose another plan.")
        return redirect(f"{reverse('superuser:tenant-register')}?step=3")
    if Tenant.objects.filter(slug=wizard_data["1"]["code"]).exists():
        messages.error(request, "That school code was registered during this session. Choose a new code.")
        return redirect(f"{reverse('superuser:tenant-register')}?step=1")
    User = get_user_model()
    if User.objects.filter(email__iexact=wizard_data["2"]["email"]).exists():
        messages.error(request, "That administrator email was registered during this session. Enter another email.")
        return redirect(f"{reverse('superuser:tenant-register')}?step=2")

    full_name = f"{wizard_data['2']['first_name']} {wizard_data['2']['last_name']}".strip()
    password_form = InitialAdministratorPasswordForm(
        request.POST if request.method == "POST" else None,
        user_email=wizard_data["2"]["email"],
        full_name=full_name,
    )
    form = None
    if request.method == "POST" and password_form.is_valid():
        try:
            tenant, _user = register_tenant(
                school=wizard_data["1"],
                administrator=wizard_data["2"],
                password=password_form.cleaned_data["password"],
                plan=plan,
                tenant_status=config["tenant_status"],
                subscription_start=datetime.fromisoformat(config["subscription_start"]).date(),
                subscription_expiry=datetime.fromisoformat(config["subscription_expiry"]).date(),
                academic_year_start=datetime.fromisoformat(config["academic_year_start"]).date(),
                academic_year_end=datetime.fromisoformat(config["academic_year_end"]).date(),
                actor=request.user,
                request=request,
            )
        except IntegrityError:
            password_form.add_error(
                None,
                "Registration could not be completed because a tenant, administrator, plan, or academic-year record conflicts with existing data. Review the earlier steps.",
            )
            return _registration_context(
                request, 4, form, wizard_data, password_form=password_form, form_status=409
            )
        except ValidationError as exc:
            password_form.add_error(None, exc)
            return _registration_context(
                request, 4, form, wizard_data, password_form=password_form, form_status=409
            )

        request.session.pop(REGISTRATION_SESSION_KEY, None)
        messages.success(request, f"{tenant.name} and its initial administrator were created.")
        return redirect(f"{reverse('superuser:tenant-directory')}?q={tenant.slug}")

    return _registration_context(request, 4, form, wizard_data, password_form=password_form)


@login_required(login_url="platform-login")
@require_POST
def cancel_tenant_registration(request):
    _require_platform_superuser(request)
    request.session.pop(REGISTRATION_SESSION_KEY, None)
    return redirect("superuser:tenant-directory")
