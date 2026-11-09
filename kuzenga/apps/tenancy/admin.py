from django.contrib import admin
from django.db import transaction

from apps.core import audit

from .forms import TenantAdminForm, primary_administrator_for_tenant
from .models import (
    Entitlement,
    Membership,
    Module,
    Plan,
    PlanModule,
    Subscription,
    SubscriptionEvent,
    Tenant,
)


class PlanModuleInline(admin.TabularInline):
    model = PlanModule
    extra = 1


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    form = TenantAdminForm
    list_display = ("name", "slug", "status", "default_currency", "timezone")
    prepopulated_fields = {"slug": ("name",)}

    fieldsets = (
        (
            "Tenant",
            {"fields": ("name", "slug", "status", "timezone", "default_currency", "country")},
        ),
        (
            "School Information and Contact Details",
            {
                "fields": (
                    "school_email",
                    "school_primary_phone",
                    "school_alternative_phone",
                    "physical_address",
                    "postal_address",
                    "website",
                    "logo",
                )
            },
        ),
    )

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        if obj is None:
            return fieldsets
        if primary_administrator_for_tenant(obj):
            fieldsets.append(
                (
                    "Primary Administrator Details",
                    {
                        "fields": (
                            "administrator_full_name",
                            "administrator_email",
                            "administrator_phone",
                            "administrator_profile_image",
                        )
                    },
                )
            )
        else:
            fieldsets.append(
                ("Primary Administrator Details", {"fields": ("primary_administrator_unavailable",)})
            )
        return fieldsets

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and primary_administrator_for_tenant(obj) is None:
            fields.append("primary_administrator_unavailable")
        return fields

    @admin.display(description="Administrator")
    def primary_administrator_unavailable(self, obj):
        return "No active owner or administrator is assigned to this tenant."

    def save_model(self, request, obj, form, change):
        previous_tenant = Tenant.objects.get(pk=obj.pk) if change else None
        previous_logo = previous_tenant.logo if previous_tenant and previous_tenant.logo else None
        primary_admin = form.primary_administrator
        user = primary_admin.user if primary_admin else None
        previous_profile = user.profile_image if user and user.profile_image else None

        super().save_model(request, obj, form, change)

        if user:
            user.full_name = form.cleaned_data["administrator_full_name"]
            user.email = form.cleaned_data["administrator_email"]
            user.phone = form.cleaned_data["administrator_phone"]
            profile_image = form.cleaned_data["administrator_profile_image"]
            if profile_image is False:
                user.profile_image = ""
            elif profile_image:
                user.profile_image = profile_image
            user.save(
                update_fields=(
                    "full_name",
                    "email",
                    "phone",
                    "profile_image",
                    "updated_at",
                )
            )

        if not change:
            audit.record(
                "tenant.created",
                actor=request.user,
                obj=obj,
                tenant=obj,
                request=request,
                changes={"status": {"before": None, "after": obj.status}},
            )
        elif form.changed_data:
            changes = audit.form_changes(
                form,
                masked_fields=(
                    "school_email",
                    "school_primary_phone",
                    "school_alternative_phone",
                    "physical_address",
                    "postal_address",
                    "website",
                    "logo",
                    "administrator_full_name",
                    "administrator_email",
                    "administrator_phone",
                    "administrator_profile_image",
                ),
            )
            audit.record(
                "tenant.profile_updated",
                actor=request.user,
                obj=obj,
                tenant=obj,
                affected_user=user,
                request=request,
                changes=changes,
            )
            administrator_fields = {
                "administrator_full_name",
                "administrator_email",
                "administrator_phone",
                "administrator_profile_image",
            }
            if user and administrator_fields.intersection(form.changed_data):
                audit.record(
                    "tenant.user_updated",
                    actor=request.user,
                    obj=primary_admin,
                    tenant=obj,
                    affected_user=user,
                    request=request,
                    changes={
                        "profile_fields_updated": sorted(
                            administrator_fields.intersection(form.changed_data)
                        )
                    },
                )
        self._delete_replaced_file(previous_logo, obj.logo)
        if user:
            self._delete_replaced_file(previous_profile, user.profile_image)

    @staticmethod
    def _delete_replaced_file(previous_file, current_file):
        if not previous_file or previous_file.name == getattr(current_file, "name", ""):
            return
        storage, old_name = previous_file.storage, previous_file.name
        transaction.on_commit(lambda: storage.delete(old_name))

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "role", "status")
    list_filter = ("tenant", "role", "status")

    def save_model(self, request, obj, form, change):
        previous = (
            Membership.objects.filter(pk=obj.pk)
            .values("role", "status")
            .first()
            if change
            else None
        )
        super().save_model(request, obj, form, change)
        audit.record(
            "tenant.user_updated" if change else "tenant.membership_created",
            actor=request.user,
            obj=obj,
            tenant=obj.tenant,
            request=request,
            changes={
                "role": {"before": previous["role"], "after": obj.role}
                if previous
                else {"before": None, "after": obj.role},
                "status": {"before": previous["status"], "after": obj.status}
                if previous
                else {"before": None, "after": obj.status},
            },
        )

    def delete_model(self, request, obj):
        audit.record(
            "tenant.membership_deleted",
            actor=request.user,
            obj=obj,
            tenant=obj.tenant,
            request=request,
            changes={"role": obj.role, "status": obj.status},
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for membership in queryset.select_related("user", "tenant").iterator():
            audit.record(
                "tenant.membership_deleted",
                actor=request.user,
                obj=membership,
                tenant=membership.tenant,
                request=request,
                changes={"role": membership.role, "status": membership.status},
            )
        queryset.delete()


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    filter_horizontal = ("depends_on",)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    inlines = [PlanModuleInline]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "plan", "status", "current_period_end")
    list_filter = ("status", "plan")

    # Writes use the platform workspace so commercial records and grants stay in sync.
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        previous = (
            Subscription.objects.filter(pk=obj.pk)
            .values("plan_id", "status", "started_at", "current_period_end", "trial_ends_at")
            .first()
            if change
            else None
        )
        super().save_model(request, obj, form, change)
        fields = ("plan_id", "status", "started_at", "current_period_end", "trial_ends_at")
        changes = {
            field: {
                "before": previous[field] if previous else None,
                "after": getattr(obj, field),
            }
            for field in fields
            if not previous or previous[field] != getattr(obj, field)
        }
        if changes:
            audit.record(
                "subscription.updated" if change else "subscription.created",
                actor=request.user,
                obj=obj,
                tenant=obj.tenant,
                request=request,
                changes=changes,
            )


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    list_display = ("tenant", "module", "source", "status", "valid_until")
    list_filter = ("tenant", "module", "status", "source")

    def save_model(self, request, obj, form, change):
        previous = (
            Entitlement.objects.filter(pk=obj.pk)
            .values("module_id", "source", "status", "valid_from", "valid_until")
            .first()
            if change
            else None
        )
        super().save_model(request, obj, form, change)
        fields = ("module_id", "source", "status", "valid_from", "valid_until")
        changes = {
            field: {
                "before": previous[field] if previous else None,
                "after": getattr(obj, field),
            }
            for field in fields
            if not previous or previous[field] != getattr(obj, field)
        }
        if changes:
            audit.record(
                "entitlement.updated",
                actor=request.user,
                obj=obj,
                tenant=obj.tenant,
                request=request,
                changes=changes,
            )


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = ("tenant", "event_type", "actor", "created_at")
    readonly_fields = [f.name for f in SubscriptionEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
