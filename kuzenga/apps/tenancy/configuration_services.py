from django.db import transaction

from apps.academics.models import AcademicYear, ClassGroup, Grade, Subject, Term
from apps.academics.services import save_record
from apps.core import audit

from .models import Tenant, TenantConfiguration


@transaction.atomic
def ensure_tenant_configuration(tenant):
    """Create the optional settings record with safe defaults, idempotently."""
    locked_tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    configuration, _created = TenantConfiguration.objects.get_or_create(tenant=locked_tenant)
    return configuration


@transaction.atomic
def save_tenant_configuration_form(*, form, tenant, actor, section, request=None):
    """Persist one already validated settings form for exactly one selected tenant."""
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    instance = form.save(commit=False)
    model = instance.__class__

    if hasattr(instance, "tenant_id"):
        instance.tenant = tenant
    if isinstance(instance, TenantConfiguration):
        instance.tenant = tenant
    if model in (AcademicYear, Term, Grade, ClassGroup, Subject):
        save_record(instance, actor=actor, request=request, platform=True)
    else:
        instance.save()
    form.save_m2m()
    audit.record(
        "tenant.configuration_changed",
        actor=actor,
        obj=tenant,
        tenant=tenant,
        request=request,
        changes=audit.form_changes(form),
        section=section,
        record_type=model._meta.label_lower,
        record_id=str(instance.pk),
    )
    return instance


@transaction.atomic
def update_regional_configuration(*, form, tenant, actor, request=None):
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    configuration = ensure_tenant_configuration(tenant)
    values = form.cleaned_data
    changes = {}
    for field in ("country", "default_currency", "timezone"):
        previous = getattr(tenant, field)
        if previous != values[field]:
            changes[field] = {"before": previous, "after": values[field]}
        setattr(tenant, field, values[field])
    for field in ("date_format", "language", "measurement_system"):
        previous = getattr(configuration, field)
        if previous != values[field]:
            changes[field] = {"before": previous, "after": values[field]}
        setattr(configuration, field, values[field])
    tenant.save(update_fields=("country", "default_currency", "timezone", "updated_at"))
    configuration.save(
        update_fields=("date_format", "language", "measurement_system", "updated_at")
    )
    audit.record(
        "tenant.configuration_changed",
        actor=actor,
        obj=tenant,
        tenant=tenant,
        request=request,
        changes=changes,
        section="regional",
    )
    return configuration


@transaction.atomic
def set_configuration_record_active(*, tenant, record, actor, active, section, request=None):
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    previous_active = record.is_active
    record.tenant = tenant
    record.is_active = active
    if isinstance(record, (Grade, ClassGroup, Subject)):
        save_record(record, actor=actor, request=request, platform=True)
    else:
        record.save(update_fields=("is_active", "updated_at"))
    audit.record(
        "tenant.configuration_changed",
        actor=actor,
        obj=tenant,
        tenant=tenant,
        request=request,
        changes={"is_active": {"before": previous_active, "after": active}},
        section=section,
        record_id=str(record.pk),
        active=active,
    )
    return record
