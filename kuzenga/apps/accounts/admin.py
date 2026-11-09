from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.core import audit

from .models import User


def _single_active_tenant(user):
    if user.is_superuser:
        return None
    from apps.tenancy.models import Membership

    memberships = list(
        Membership.objects.filter(user=user, status=Membership.Status.ACTIVE)
        .select_related("tenant")[:2]
    )
    return memberships[0].tenant if len(memberships) == 1 else None


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "full_name", "is_staff", "is_active")
    search_fields = ("email", "full_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name",)}),
        (
            "Platform access",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def save_model(self, request, obj, form, change):
        previous = None
        if change:
            previous = User.objects.filter(pk=obj.pk).values(
                "email", "full_name", "phone", "is_active", "is_staff", "is_superuser"
            ).first()
        super().save_model(request, obj, form, change)
        changed = set(form.changed_data)
        if not change:
            action = "user.created"
            changes = {"account": {"before": None, "after": "created"}}
        else:
            changes = {}
            for field in changed:
                if field in {"is_active", "is_staff", "is_superuser"} and previous is not None:
                    changes[field] = {"before": previous[field], "after": getattr(obj, field)}
                elif field not in {"password", "last_login"}:
                    changes[field] = "[REDACTED]" if audit.is_sensitive_key(field) else {"changed": True}
            if not changes:
                return
            if changed.intersection({"is_staff", "is_superuser", "groups", "user_permissions"}):
                action = "security.platform_privilege_changed"
            else:
                action = "user.status_changed" if "is_active" in changed else "user.profile_updated"

        audit.record(
            action,
            actor=request.user,
            obj=obj,
            tenant=_single_active_tenant(obj),
            request=request,
            changes=changes,
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url=form_url)
        if request.method == "POST" and response.status_code in (302, 303):
            user = self.get_object(request, id)
            if user is not None:
                audit.record(
                    "user.password_reset_completed",
                    actor=request.user,
                    obj=user,
                    tenant=_single_active_tenant(user),
                    request=request,
                )
        return response
