import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_anonymous_root_opens_corporate_home(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Elevating Ideas." in response.content
    assert reverse("login").encode() in response.content


@pytest.mark.django_db
def test_platform_superuser_root_opens_tenant_directory_without_loop(client):
    superuser = User.objects.create_superuser("platform-entry@example.test", "Unused-password-1!")
    client.force_login(superuser)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert response.url == reverse("superuser:tenant-directory")
    assert client.get(response.url).status_code == 200


@pytest.mark.django_db
def test_school_administrator_root_opens_school_dashboard(client, admin_a):
    client.force_login(admin_a)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert b"Welcome" in response.content


@pytest.mark.django_db
def test_school_administrator_login_and_logout_keep_working(client, admin_a):
    login = client.post(
        reverse("login"), {"username": admin_a.email, "password": "pass12345!"}
    )

    assert login.status_code == 302
    assert login.url == reverse("dashboard")
    assert client.get(login.url).status_code == 200

    logout = client.post(reverse("logout"))
    assert logout.status_code == 302
    assert logout.url == reverse("login")


@pytest.mark.django_db
def test_platform_superuser_login_uses_dashboard_even_with_admin_return_target(client):
    superuser = User.objects.create_superuser(
        "platform-login@example.test", "Unused-password-1!"
    )

    response = client.post(
        f"{reverse('platform-login')}?next=/admin/",
        {"username": superuser.email, "password": "Unused-password-1!"},
    )

    assert response.status_code == 302
    assert response.url == reverse("superuser:tenant-directory")
    assert client.get(response.url).status_code == 200


@pytest.mark.django_db
def test_superuser_credentials_are_rejected_by_school_portal(client):
    superuser = User.objects.create_superuser("platform-only@example.test", "Unused-password-1!")

    response = client.post(
        reverse("login"),
        {"username": superuser.email, "password": "Unused-password-1!"},
    )

    assert response.status_code == 200
    assert "Incorrect email or password." in response.content.decode()


@pytest.mark.django_db
def test_authenticated_user_without_tenant_context_goes_to_tenant_selection(client):
    user = User.objects.create_user("unassigned-entry@example.test", "Unused-password-1!")
    client.force_login(user)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert response.url == reverse("tenancy:select")
    assert client.get(response.url).status_code == 200
