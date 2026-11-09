from unittest.mock import patch

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError, connections
from django.urls import reverse
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework.test import APIClient


def test_custom_user_model_remains_authoritative():
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert get_user_model()._meta.label == "accounts.User"


def test_all_existing_applications_remain_installed():
    for app_name in (
        "apps.core",
        "apps.accounts",
        "apps.tenancy",
        "apps.academics",
        "apps.students",
        "apps.attendance",
        "rest_framework",
    ):
        assert apps.is_installed(app_name)


def test_drf_defaults_are_authenticated_session_only():
    assert api_settings.DEFAULT_PERMISSION_CLASSES == [IsAuthenticated]
    assert api_settings.DEFAULT_AUTHENTICATION_CLASSES == [SessionAuthentication]


def test_existing_browser_routes_still_resolve():
    for route_name in (
        "dashboard",
        "login",
        "logout",
        "health",
        "tenancy:select",
        "academics:overview",
        "students:list",
        "attendance:today",
    ):
        assert reverse(route_name)


def test_static_and_media_settings_are_configured():
    assert settings.STATIC_URL == "/static/"
    assert settings.STATIC_ROOT.name == "staticfiles"
    assert settings.MEDIA_URL == "/media/"
    assert settings.MEDIA_ROOT.name == "media"


@pytest.mark.django_db
def test_health_routes_remain_public_and_report_database_status():
    client = APIClient()

    for route_name in ("health", "api-health"):
        response = client.get(reverse(route_name))
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_health_reports_database_unavailable():
    client = APIClient()
    with patch.object(connections["default"], "ensure_connection", side_effect=OperationalError):
        response = client.get(reverse("health"))

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unavailable"}
