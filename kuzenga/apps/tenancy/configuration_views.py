from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.academics.models import (
    AcademicYear,
    AssessmentCategory,
    ClassGroup,
    Department,
    Grade,
    GradeBoundary,
    SchoolCalendarEvent,
    Subject,
    Term,
)
from apps.core import audit

from .configuration_forms import (
    SECTION_CONFIG,
    AttendanceConfigurationForm,
    NotificationConfigurationForm,
    RegionalConfigurationForm,
    TenantIdentityForm,
)
from .configuration_services import (
    ensure_tenant_configuration,
    save_tenant_configuration_form,
    set_configuration_record_active,
    update_regional_configuration,
)
from .models import Tenant
from .views import PLATFORM_NAVIGATION

SETTINGS_SECTIONS = {
    "identity": {"title": "School identity and branding", "form": TenantIdentityForm},
    "regional": {"title": "Regional and localization settings", "form": RegionalConfigurationForm},
    "attendance": {"title": "Attendance settings", "form": AttendanceConfigurationForm},
    "notifications": {"title": "Notifications and communication", "form": NotificationConfigurationForm},
}

SECTION_NAV = (
    ("identity", "School identity"),
    ("regional", "Regional settings"),
    ("academic-years", "Academic years"),
    ("terms", "Terms and semesters"),
    ("calendar", "Calendar and holidays"),
    ("levels", "Education levels"),
    ("classes", "Classes and streams"),
    ("departments", "Departments"),
    ("subjects", "Subjects"),
    ("assessment", "Assessment types"),
    ("grading", "Grading scale"),
    ("attendance", "Attendance"),
    ("notifications", "Notifications"),
)


def _require_platform_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _tenant_configuration(tenant):
    return ensure_tenant_configuration(tenant)


@login_required(login_url="platform-login")
@require_http_methods(["GET"])
def tenant_configuration(request, tenant_id):
    _require_platform_superuser(request)
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    configuration = _tenant_configuration(tenant)
    counts = {
        "academic_years": AcademicYear.unscoped.filter(tenant=tenant).count(),
        "terms": Term.unscoped.filter(tenant=tenant).count(),
        "calendar_events": SchoolCalendarEvent.unscoped.filter(tenant=tenant).count(),
        "levels": Grade.unscoped.filter(tenant=tenant).count(),
        "classes": ClassGroup.unscoped.filter(tenant=tenant).count(),
        "departments": Department.unscoped.filter(tenant=tenant).count(),
        "subjects": Subject.unscoped.filter(tenant=tenant).count(),
        "assessment_categories": AssessmentCategory.unscoped.filter(tenant=tenant).count(),
        "grade_boundaries": GradeBoundary.unscoped.filter(tenant=tenant).count(),
    }
    return render(
        request,
        "superuser/tenants/configuration.html",
        {
            "tenant": tenant,
            "configuration": configuration,
            "counts": counts,
            "sections": SECTION_NAV,
            "platform_navigation": PLATFORM_NAVIGATION,
            "active_section": "tenant-configuration",
        },
    )


def _section_context(request, tenant, section, form, *, instance=None, status=200):
    spec = SECTION_CONFIG.get(section)
    query = spec["model"].unscoped.filter(tenant=tenant)
    related = {
        "terms": ("academic_year",),
        "calendar": ("academic_year",),
        "classes": ("academic_year", "grade"),
    }.get(section, ())
    if related:
        query = query.select_related(*related)
    records = list(query.order_by("-created_at")[:200])
    rows = [
        {"record": record, "values": [getattr(record, field) for field in spec["fields"]]}
        for record in records
    ]
    return render(
        request,
        "superuser/tenants/configuration_section.html",
        {
            "tenant": tenant,
            "section": section,
            "title": spec["title"],
            "field_names": spec["fields"],
            "active_field": spec["active_field"],
            "records": records,
            "rows": rows,
            "form": form,
            "instance": instance,
            "sections": SECTION_NAV,
            "active_section": "tenant-configuration",
            "platform_navigation": PLATFORM_NAVIGATION,
            "configuration_url": reverse("superuser:tenant-configuration", args=[tenant.pk]),
        },
        status=status,
    )


@login_required(login_url="platform-login")
@require_http_methods(["GET", "POST"])
def tenant_configuration_section(request, tenant_id, section, record_id=None):
    _require_platform_superuser(request)
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    configuration = _tenant_configuration(tenant)

    if section in SETTINGS_SECTIONS:
        title = SETTINGS_SECTIONS[section]["title"]
        if section == "identity":
            form = TenantIdentityForm(
                request.POST or None,
                request.FILES or None,
                instance=tenant,
            )
        elif section == "regional":
            form = RegionalConfigurationForm(
                request.POST or None,
                tenant=tenant,
                configuration=configuration,
            )
        else:
            form_class = (
                AttendanceConfigurationForm
                if section == "attendance"
                else NotificationConfigurationForm
            )
            form = form_class(request.POST or None, instance=configuration)

        if request.method == "POST" and form.is_valid():
            if section == "identity":
                old_logo = tenant.logo
                with transaction.atomic():
                    tenant = form.save()
                    audit.record(
                        "tenant.configuration_changed",
                        actor=request.user,
                        obj=tenant,
                        tenant=tenant,
                        request=request,
                        changes=audit.form_changes(form),
                        section=section,
                    )
                    if old_logo and old_logo.name != getattr(tenant.logo, "name", ""):
                        transaction.on_commit(lambda: old_logo.storage.delete(old_logo.name))
            elif section == "regional":
                update_regional_configuration(
                    form=form, tenant=tenant, actor=request.user, request=request
                )
            else:
                save_tenant_configuration_form(
                    form=form,
                    tenant=tenant,
                    actor=request.user,
                    section=section,
                    request=request,
                )
            messages.success(request, f"{title} saved for {tenant.name}.")
            return redirect("superuser:tenant-configuration-section", tenant_id=tenant.pk, section=section)

        return render(
            request,
            "superuser/tenants/configuration_settings.html",
            {
                "tenant": tenant,
                "configuration": configuration,
                "section": section,
                "title": title,
                "form": form,
                "sections": SECTION_NAV,
                "active_section": "tenant-configuration",
                "platform_navigation": PLATFORM_NAVIGATION,
                "configuration_url": reverse("superuser:tenant-configuration", args=[tenant.pk]),
            },
            status=200 if form.is_valid() or request.method == "GET" else 400,
        )

    spec = SECTION_CONFIG.get(section)
    if spec is None:
        from django.http import Http404

        raise Http404
    model = spec["model"]
    instance = get_object_or_404(model.unscoped.filter(tenant=tenant), pk=record_id) if record_id else None
    form = spec["form"](request.POST or None, tenant=tenant, instance=instance)
    if request.method == "POST" and form.is_valid():
        try:
            save_tenant_configuration_form(
                form=form,
                tenant=tenant,
                actor=request.user,
                section=section,
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"{spec['title']} saved for {tenant.name}.")
            return redirect("superuser:tenant-configuration-section", tenant_id=tenant.pk, section=section)
    return _section_context(
        request,
        tenant,
        section,
        form,
        instance=instance,
        status=200 if form.is_valid() or request.method == "GET" else 400,
    )


@login_required(login_url="platform-login")
@require_POST
def tenant_configuration_toggle(request, tenant_id, section, record_id):
    _require_platform_superuser(request)
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    spec = SECTION_CONFIG.get(section)
    if spec is None or not spec["active_field"]:
        from django.http import Http404

        raise Http404
    record = get_object_or_404(spec["model"].unscoped.filter(tenant=tenant), pk=record_id)
    active = request.POST.get("active") == "true"
    set_configuration_record_active(
        tenant=tenant,
        record=record,
        actor=request.user,
        active=active,
        section=section,
        request=request,
    )
    state = "activated" if active else "deactivated"
    messages.success(request, f"{record} was {state}.")
    return redirect("superuser:tenant-configuration-section", tenant_id=tenant.pk, section=section)

