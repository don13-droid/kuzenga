from django.contrib import admin

from .models import AuditEvent, DemoEnquiry


class TenantScopedAdmin(admin.ModelAdmin):
    """Platform-admin view of tenant-owned data (bypasses tenant scoping on purpose)."""

    list_filter = ("tenant",)

    def get_queryset(self, request):
        return self.model.unscoped.all()


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "category", "action", "outcome", "tenant", "actor", "target_user")
    list_filter = ("tenant", "category", "action", "outcome")
    search_fields = ("action", "description", "actor__email", "target_user__email", "tenant__name")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DemoEnquiry)
class DemoEnquiryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organisation", "plan", "enrolment")
    readonly_fields = [field.name for field in DemoEnquiry._meta.fields]

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
