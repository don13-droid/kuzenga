from django.contrib.auth.views import LoginView
from django.db import DatabaseError, connections
from django.shortcuts import redirect, render
from django.urls import reverse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.forms import PlatformAuthenticationForm, SchoolAuthenticationForm
from apps.tenancy.services import has_module


class PortalLoginView(LoginView):
    """Authenticate school/client users through the school portal."""

    authentication_form = SchoolAuthenticationForm


class PlatformLoginView(LoginView):
    """Authenticate only platform superusers through their dedicated portal."""

    authentication_form = PlatformAuthenticationForm
    template_name = "registration/superuser_login.html"

    def get_success_url(self):
        return reverse("superuser:tenant-directory")


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    """Return coarse service health and verify that the configured database is reachable."""
    try:
        connections["default"].ensure_connection()
    except DatabaseError:
        return Response(
            {"status": "unhealthy", "database": "unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({"status": "ok", "database": "ok"}, status=status.HTTP_200_OK)


def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if request.user.is_superuser:
        return redirect("superuser:tenant-directory")
    if request.tenant is None:
        return redirect("tenancy:select")

    stats = []
    if has_module(request.tenant, "students"):
        from apps.students.models import Student

        stats.append(("Active learners", Student.objects.filter(status="active").count()))
    if has_module(request.tenant, "academics"):
        from apps.academics.models import ClassGroup

        stats.append(("Classes", ClassGroup.objects.count()))
    return render(request, "dashboard/index.html", {"stats": stats})
