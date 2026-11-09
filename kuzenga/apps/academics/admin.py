from django.contrib import admin

from apps.core.admin import TenantScopedAdmin

from .models import AcademicYear, ClassGroup, Grade, Subject, Term

for model in (AcademicYear, Term, Grade, ClassGroup, Subject):
    admin.site.register(model, TenantScopedAdmin)
