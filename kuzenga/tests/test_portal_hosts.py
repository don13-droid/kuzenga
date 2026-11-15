import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from apps.core.hosts import PortalHostMiddleware

PUBLIC_HOST = "www.elevondigital.com"
PLATFORM_HOST = "platform.kuzenga.elevondigitalzw.com"
CLIENT_HOST = "kuzenga.elevondigitalzw.com"


@pytest.fixture
def portal_hosts(settings):
    settings.PUBLIC_SITE_HOST = PUBLIC_HOST
    settings.PLATFORM_SITE_HOST = PLATFORM_HOST
    settings.CLIENT_SITE_HOST = CLIENT_HOST
    settings.ALLOWED_HOSTS = [PUBLIC_HOST, PLATFORM_HOST, CLIENT_HOST, "testserver"]


@pytest.mark.django_db
def test_landing_host_renders_marketing_and_links_to_separate_portals(client, portal_hosts):
    response = client.get("/", HTTP_HOST=PUBLIC_HOST)
    assert response.status_code == 200
    assert b"Elevating Ideas." in response.content
    assert f'https://{CLIENT_HOST}/login/'.encode() in response.content
    assert f'https://{PLATFORM_HOST}/platform/login/'.encode() in response.content


@pytest.mark.django_db
@pytest.mark.parametrize("host,path,target", [
    (PLATFORM_HOST, "/", f"https://{PLATFORM_HOST}/platform/login/"),
    (PLATFORM_HOST, "/login/", f"https://{PLATFORM_HOST}/platform/login/"),
    (CLIENT_HOST, "/", f"https://{CLIENT_HOST}/login/"),
    (CLIENT_HOST, "/platform/login/", f"https://{PLATFORM_HOST}/platform/login/"),
    (PUBLIC_HOST, "/login/?next=/dashboard/", f"https://{CLIENT_HOST}/login/?next=/dashboard/"),
    (PUBLIC_HOST, "/platform/login/", f"https://{PLATFORM_HOST}/platform/login/"),
    (PLATFORM_HOST, "/students/", f"https://{CLIENT_HOST}/students/"),
    (CLIENT_HOST, "/elevon/", f"https://{PUBLIC_HOST}/elevon/"),
    (PLATFORM_HOST, "/elevon/", f"https://{PUBLIC_HOST}/elevon/"),
])
def test_portal_entry_routes_to_its_configured_host(client, portal_hosts, host, path, target):
    response = client.get(path, HTTP_HOST=host)
    assert response.status_code == 302
    assert response.url == target


@pytest.mark.django_db
def test_authenticated_school_root_opens_dashboard(client, admin_a, portal_hosts):
    client.force_login(admin_a)
    response = client.get("/", HTTP_HOST=CLIENT_HOST)
    assert response.url == f"https://{CLIENT_HOST}{reverse('dashboard')}"


@pytest.mark.django_db
def test_platform_superuser_root_opens_tenant_directory(client, portal_hosts):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.create_superuser("host-entry@example.test", "Unused-password-1!")
    client.force_login(user)
    response = client.get("/", HTTP_HOST=PLATFORM_HOST)
    assert response.url == f"https://{PLATFORM_HOST}{reverse('superuser:tenant-directory')}"


@pytest.mark.django_db
def test_platform_login_and_logout_stay_on_platform_host(client, portal_hosts):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.create_superuser("host-session@example.test", "Unused-password-1!")
    response = client.post(reverse("platform-login"), {
        "username": user.email, "password": "Unused-password-1!",
    }, HTTP_HOST=PLATFORM_HOST)
    assert response.status_code == 302
    assert response.url == reverse("superuser:tenant-directory")
    assert client.get(response.url, HTTP_HOST=PLATFORM_HOST).status_code == 200
    logout = client.post(reverse("platform-logout"), HTTP_HOST=PLATFORM_HOST)
    assert logout.url == reverse("platform-login")
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@pytest.mark.parametrize("host,path", [
    (PUBLIC_HOST, "/login/"),
    (PLATFORM_HOST, "/login/"),
    (CLIENT_HOST, "/platform/login/"),
])
def test_wrong_portal_does_not_forward_or_accept_login_credentials(client, admin_a, portal_hosts, host, path):
    response = client.post(path, {"username": admin_a.email, "password": "pass12345!"}, HTTP_HOST=host)
    assert response.status_code == 404
    assert "Location" not in response
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_unconfigured_preview_keeps_existing_entry_behavior(client, portal_hosts):
    response = client.get("/", HTTP_HOST="testserver")
    assert response.status_code == 200
    assert b"Elevating Ideas." in response.content


@pytest.mark.parametrize("overrides", [
    {"CLIENT_SITE_HOST": ""},
    {"CLIENT_SITE_HOST": PLATFORM_HOST},
    {"CLIENT_SITE_HOST": "https://school.example.test"},
    {"CLIENT_SITE_HOST": "*.example.test"},
    {"ALLOWED_HOSTS": [PUBLIC_HOST, PLATFORM_HOST]},
])
def test_invalid_portal_configuration_fails_closed(settings, portal_hosts, overrides):
    for key, value in overrides.items():
        setattr(settings, key, value)
    with pytest.raises(ImproperlyConfigured):
        PortalHostMiddleware(lambda request: None)
