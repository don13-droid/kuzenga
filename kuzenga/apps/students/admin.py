from django.contrib import admin

from apps.core.admin import TenantScopedAdmin

from .models import Guardian, Student, StudentEnrolment, StudentGuardian

for model in (Student, Guardian, StudentGuardian, StudentEnrolment):
    admin.site.register(model, TenantScopedAdmin)
