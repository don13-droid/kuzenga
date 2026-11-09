from django.contrib import admin

from apps.core.admin import TenantScopedAdmin

from .models import AttendanceRecord, AttendanceSession

for model in (AttendanceSession, AttendanceRecord):
    admin.site.register(model, TenantScopedAdmin)
