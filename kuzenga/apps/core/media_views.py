"""Serve only referenced images, with record-level authorization in every environment."""

from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET

from apps.accounts.models import User
from apps.tenancy.models import Tenant
from apps.tenancy.permissions import has_permission


@login_required
@require_GET
def image(request, path):
    platform = request.user.is_active and request.user.is_superuser
    tenant = getattr(request, "tenant", None)
    field = None
    if path.startswith("tenant-logos/"):
        schools = Tenant.objects.all() if platform else Tenant.objects.filter(pk=getattr(tenant, "pk", None))
        record = schools.filter(logo=path).first()
        field = record.logo if record else None
    elif path.startswith("user-profile-images/"):
        people = User.objects.filter(profile_image=path)
        if not platform:
            if has_permission(getattr(request, "membership", None), "users.view"):
                people = people.filter(memberships__tenant=tenant)
            else:
                people = people.filter(pk=request.user.pk)
        person = people.first()
        field = person.profile_image if person else None
    elif path.startswith("student-images/"):
        from apps.students.models import Student
        from apps.tenancy.services import has_module

        if tenant and has_module(tenant, "students") and has_permission(request.membership, "students.view"):
            student = Student.objects.filter(profile_image=path).first()
            field = student.profile_image if student else None
    if not field:
        raise Http404
    content_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        Path(field.name).suffix.lower()
    )
    if content_type is None:
        raise Http404
    try:
        stream = field.storage.open(field.name, "rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404 from exc
    response = FileResponse(stream, content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
