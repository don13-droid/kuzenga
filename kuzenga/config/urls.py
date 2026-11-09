from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core.media_views import image
from apps.core.views import PlatformLoginView, PortalLoginView, dashboard, health
from apps.tenancy import user_admin_views

urlpatterns = [
    path("media/<path:path>", image, name="protected-image"),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/health/", health, name="api-health"),
    path("login/", PortalLoginView.as_view(), name="login"),
    path("platform/login/", PlatformLoginView.as_view(), name="platform-login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("platform/logout/", auth_views.LogoutView.as_view(next_page="platform-login"), name="platform-logout"),
    path(
        "account/activate/<uuid:tenant_id>/<uuid:membership_id>/<str:uidb64>/<str:token>/",
        user_admin_views.activate_tenant_member,
        name="tenant-user-activate",
    ),
    path(
        "account/password-reset/<uuid:tenant_id>/<uuid:membership_id>/<str:uidb64>/<str:token>/",
        user_admin_views.reset_tenant_member_password_view,
        name="tenant-user-password-reset-confirm",
    ),
    path("", dashboard, name="dashboard"),
    path("school/", include("apps.tenancy.urls")),
    path("platform/", include("apps.tenancy.superuser_urls")),
    path("academics/", include("apps.academics.urls")),
    path("students/", include("apps.students.urls")),
    path("admissions/", include("apps.admissions.urls")),
    path("attendance/", include("apps.attendance.urls")),
]
