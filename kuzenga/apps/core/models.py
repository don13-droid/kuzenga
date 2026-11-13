import uuid

from django.conf import settings
from django.db import models

from .context import get_current_tenant
from .exceptions import TenantContextMissing, TenantMismatch


class TimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantManager(models.Manager):
    """Default manager for tenant-owned models. Fails CLOSED: no tenant context -> no rows."""

    def get_queryset(self):
        tenant = get_current_tenant()
        qs = super().get_queryset()
        if tenant is None:
            return qs.none()
        return qs.filter(tenant_id=tenant.id)


class TenantScopedModel(TimeStampedModel):
    """Base for every tenant-owned record.

    - `objects` is tenant-scoped automatically (from the active tenant context).
    - `unscoped` is for platform admin / migrations / tests only. Never use in school views.
    - save() sets the tenant, refuses cross-tenant writes and cross-tenant foreign keys.
    NOTE: bulk_create/bulk_update/queryset.update() bypass save(); use with care.
    """

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="+")

    objects = TenantManager()
    unscoped = models.Manager()

    class Meta:
        abstract = True

    def _check_related_tenants(self):
        for field in self._meta.concrete_fields:
            if not (field.is_relation and field.many_to_one) or field.name == "tenant":
                continue
            if not issubclass(field.related_model, TenantScopedModel):
                continue
            if getattr(self, field.attname) is None:
                continue
            related = getattr(self, field.name)
            if related.tenant_id != self.tenant_id:
                raise TenantMismatch(f"{field.name} belongs to a different tenant")

    def save(self, *args, **kwargs):
        current = get_current_tenant()
        if self.tenant_id is None:
            if current is None:
                raise TenantContextMissing("No active tenant for this write")
            self.tenant = current
        elif current is not None and self.tenant_id != current.id:
            raise TenantMismatch("Record belongs to a different tenant than the active one")
        self._check_related_tenants()
        super().save(*args, **kwargs)


class AuditEventQuerySet(models.QuerySet):
    """Prevent ordinary ORM APIs from rewriting or deleting audit history."""

    def update(self, **kwargs):
        raise RuntimeError("Audit events are immutable")

    def delete(self):
        raise RuntimeError("Audit events are immutable")

    def bulk_update(self, objs, fields, batch_size=None):
        raise RuntimeError("Audit events are immutable")


class AuditEvent(models.Model):
    """Append-only history of sensitive actions."""

    class Category(models.TextChoices):
        TENANT = "tenant", "Tenant administration"
        USER = "user_management", "User management"
        AUTHENTICATION = "authentication", "Authentication"
        CONFIGURATION = "configuration", "Tenant configuration"
        SUBSCRIPTION = "subscription", "Subscription"
        SECURITY = "security", "Security"
        OTHER = "other", "Other"

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenancy.Tenant", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    action = models.CharField(max_length=100, db_index=True)
    category = models.CharField(
        max_length=24, choices=Category.choices, default=Category.OTHER, db_index=True
    )
    description = models.CharField(max_length=255, blank=True)
    outcome = models.CharField(max_length=12, choices=Outcome.choices, default=Outcome.SUCCESS)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_method = models.CharField(max_length=10, blank=True)
    request_route = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="audit_tenant_time_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_time_idx"),
            models.Index(fields=["target_user", "-created_at"], name="audit_target_time_idx"),
            models.Index(fields=["category", "-created_at"], name="audit_category_time_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Audit events are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit events are immutable")

    def __str__(self):
        return f"{self.created_at}: {self.action}"


class DemoEnquiry(models.Model):
    """Platform-owned leads, never exposed through school querysets or public reads."""

    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=120)
    organisation = models.CharField(max_length=200)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=40)
    enrolment = models.PositiveIntegerField()
    plan = models.CharField(max_length=20)
    message = models.TextField(max_length=4000)
    consent = models.BooleanField()
