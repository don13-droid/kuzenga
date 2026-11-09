from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import AcademicYear
from apps.core.models import AuditEvent
from apps.tenancy.models import Membership, Plan, Role, Subscription, Tenant, TenantConfiguration

User = get_user_model()
WIZARD_URL = "superuser:tenant-register"


def school_data(**overrides):
    return {
        "name": "New Registration School",
        "code": "new-registration-school",
        "country": "zw",
        "timezone": "Africa/Harare",
        "default_currency": "USD",
        **overrides,
    }


def administrator_data(**overrides):
    return {
        "first_name": "Rudo",
        "last_name": "Moyo",
        "email": "rudo.moyo@example.test",
        **overrides,
    }


def configuration_data(**overrides):
    today = timezone.localdate()
    return {
        "plan": str(Plan.objects.get(code="standard").pk),
        "subscription_start": today.isoformat(),
        "subscription_expiry": (today + timedelta(days=90)).isoformat(),
        "tenant_status": Tenant.Status.ACTIVE,
        "academic_year_start": date(today.year, 1, 1).isoformat(),
        "academic_year_end": date(today.year, 12, 31).isoformat(),
        **overrides,
    }


def submit_prior_steps(client, configuration=None):
    client.post(reverse(WIZARD_URL), {"step": 1, **school_data()})
    client.post(reverse(WIZARD_URL), {"step": 2, **administrator_data()})
    client.post(reverse(WIZARD_URL), {"step": 3, **configuration_data(**(configuration or {}))})


def submit_creation(client, password="A-Very-Strong-Password-925!"):
    return client.post(
        reverse(WIZARD_URL),
        {
            "step": 4,
            "password": password,
            "password_confirmation": password,
            "action": "create",
        },
    )


@pytest.mark.django_db
def test_registration_creates_tenant_owner_subscription_and_academic_year(client):
    platform_user = User.objects.create_superuser("platform-reg@example.test", "not-used")
    client.force_login(platform_user)
    plan = Plan.objects.get(code="standard")
    submit_prior_steps(client, {"plan": str(plan.pk)})
    response = submit_creation(client)

    tenant = Tenant.objects.get(slug="new-registration-school")
    administrator = User.objects.get(email="rudo.moyo@example.test")
    membership = Membership.objects.get(user=administrator, tenant=tenant)
    subscription = Subscription.objects.get(tenant=tenant)
    academic_year = AcademicYear.unscoped.get(tenant=tenant)
    tenant_configuration = TenantConfiguration.objects.get(tenant=tenant)

    assert response.status_code == 302
    assert response.url == f"{reverse('superuser:tenant-directory')}?q={tenant.slug}"
    assert tenant.status == Tenant.Status.ACTIVE
    assert tenant.country == "ZW"
    assert membership.role == Role.OWNER
    assert membership.status == Membership.Status.ACTIVE
    assert administrator.full_name == "Rudo Moyo"
    assert administrator.check_password("A-Very-Strong-Password-925!")
    assert subscription.plan == plan
    assert subscription.status == Subscription.Status.ACTIVE
    assert subscription.started_at.date() == timezone.localdate()
    assert subscription.current_period_end.date() == timezone.localdate() + timedelta(days=90)
    assert academic_year.is_current
    assert academic_year.start_date == date(timezone.localdate().year, 1, 1)
    assert tenant_configuration.late_arrival_threshold_minutes == 15
    assert tenant_configuration.notify_by_email
    assert "tenant_registration_wizard" not in client.session
    registration_event = AuditEvent.objects.get(tenant=tenant, action="tenant.created")
    subscription_event = AuditEvent.objects.get(tenant=tenant, action="subscription.activated")
    assert registration_event.actor == platform_user
    assert registration_event.target_user == administrator
    assert registration_event.request_method == "POST"
    assert registration_event.category == AuditEvent.Category.TENANT
    assert subscription_event.actor == platform_user
    assert registration_event.changes["status"]["after"] == Tenant.Status.ACTIVE
    assert "A-Very-Strong-Password-925!" not in str(registration_event.metadata)
    assert "A-Very-Strong-Password-925!" not in str(registration_event.changes)


@pytest.mark.django_db
def test_directory_register_button_opens_shared_registration_wizard(client):
    client.force_login(User.objects.create_superuser("platform-button@example.test", "unused"))

    directory = client.get(reverse("superuser:tenant-directory"))
    wizard_url = reverse(WIZARD_URL)
    wizard = client.get(wizard_url)

    assert directory.status_code == 200
    assert f'href="{wizard_url}"'.encode() in directory.content
    assert b'href="/admin/"' not in directory.content
    assert wizard.status_code == 200
    assert b"Register New Tenant" in wizard.content
    assert b"Superuser navigation" in wizard.content
    assert b'href="/admin/"' not in wizard.content
    assert b'name="csrfmiddlewaretoken"' in wizard.content


@pytest.mark.django_db
def test_superuser_sidebar_shell_has_viewport_sizing_and_internal_scroll(client):
    client.force_login(User.objects.create_superuser("platform-sidebar@example.test", "unused"))

    response = client.get(reverse(WIZARD_URL))
    html = response.content.decode()

    assert "md:fixed md:inset-y-0" in html
    assert "md:flex-1" in html
    assert "md:overflow-y-auto" in html
    assert "min-h-0" in html
    assert "md:ml-64" in html
    assert "overflow-x-hidden" in html
    assert 'aria-current="page"' in html


@pytest.mark.django_db
def test_trial_tenant_uses_trial_subscription(client):
    client.force_login(User.objects.create_superuser("platform-trial@example.test", "not-used"))
    submit_prior_steps(client, {"tenant_status": Tenant.Status.TRIAL})
    response = submit_creation(client)

    tenant = Tenant.objects.get(slug="new-registration-school")
    subscription = Subscription.objects.get(tenant=tenant)
    assert response.status_code == 302
    assert tenant.status == Tenant.Status.TRIAL
    assert subscription.status == Subscription.Status.TRIAL
    assert subscription.trial_ends_at == subscription.current_period_end


@pytest.mark.parametrize("tenant_status", [Tenant.Status.SUSPENDED, Tenant.Status.ARCHIVED])
@pytest.mark.django_db
def test_restricted_tenant_statuses_create_no_active_entitlements(client, tenant_status):
    client.force_login(User.objects.create_superuser(f"platform-{tenant_status}@example.test", "unused"))
    submit_prior_steps(client, {"tenant_status": tenant_status})

    response = submit_creation(client)

    tenant = Tenant.objects.get(slug="new-registration-school")
    subscription = Subscription.objects.get(tenant=tenant)
    assert response.status_code == 302
    assert tenant.status == tenant_status
    assert subscription.status == Subscription.Status.SUSPENDED
    assert not tenant.entitlements.filter(status="active").exists()


@pytest.mark.django_db
def test_registration_rejects_duplicate_tenant_code(client):
    Tenant.objects.create(name="Existing", slug="new-registration-school")
    client.force_login(User.objects.create_superuser("platform-code@example.test", "unused"))

    response = client.post(reverse(WIZARD_URL), {"step": 1, **school_data()})

    assert response.status_code == 200
    assert b"A tenant with this school code already exists" in response.content
    assert Tenant.objects.filter(slug="new-registration-school").count() == 1


@pytest.mark.django_db
def test_registration_rejects_duplicate_administrator_email(client):
    User.objects.create_user("rudo.moyo@example.test", "Existing-Password-982!")
    client.force_login(User.objects.create_superuser("platform-email@example.test", "unused"))
    client.post(reverse(WIZARD_URL), {"step": 1, **school_data()})

    response = client.post(reverse(WIZARD_URL), {"step": 2, **administrator_data()})

    assert response.status_code == 200
    assert b"An account already uses this email address" in response.content
    assert not Tenant.objects.filter(slug="new-registration-school").exists()


@pytest.mark.django_db
def test_registration_validates_subscription_and_academic_dates(client):
    client.force_login(User.objects.create_superuser("platform-dates@example.test", "unused"))
    client.post(reverse(WIZARD_URL), {"step": 1, **school_data()})
    client.post(reverse(WIZARD_URL), {"step": 2, **administrator_data()})
    today = timezone.localdate()
    configuration = configuration_data(
        subscription_start=today.isoformat(),
        subscription_expiry=today.isoformat(),
        academic_year_start=date(today.year, 1, 1).isoformat(),
        academic_year_end=date(today.year, 1, 1).isoformat(),
    )

    response = client.post(reverse(WIZARD_URL), {"step": 3, **configuration})

    assert response.status_code == 200
    assert b"Expiry must be after the start date" in response.content
    assert b"The academic year end must be after its start" in response.content
    assert not Tenant.objects.filter(slug="new-registration-school").exists()


@pytest.mark.django_db
def test_registration_rejects_mismatched_initial_passwords(client):
    client.force_login(User.objects.create_superuser("platform-password@example.test", "unused"))
    submit_prior_steps(client)

    response = client.post(
        reverse(WIZARD_URL),
        {
            "step": 4,
            "password": "A-Very-Strong-Password-925!",
            "password_confirmation": "Different-Password-927!",
        },
    )

    assert response.status_code == 200
    assert b"The passwords do not match" in response.content
    assert not Tenant.objects.filter(slug="new-registration-school").exists()


@pytest.mark.django_db
def test_registration_requires_platform_superuser(client, admin_a):
    url = reverse(WIZARD_URL)
    assert client.get(url).status_code == 302
    client.force_login(admin_a)
    assert client.get(url).status_code == 403
    assert client.post(url, {"step": 1, **school_data()}).status_code == 403


@pytest.mark.django_db
def test_registration_rolls_back_every_record_on_subscription_failure(client, monkeypatch):
    client.force_login(User.objects.create_superuser("platform-rollback@example.test", "unused"))
    submit_prior_steps(client)

    def fail_activation(*args, **kwargs):
        raise IntegrityError("simulated subscription constraint failure")

    monkeypatch.setattr("apps.tenancy.services.activate_plan", fail_activation)
    response = submit_creation(client)

    assert response.status_code == 409
    assert not Tenant.objects.filter(slug="new-registration-school").exists()
    assert not User.objects.filter(email="rudo.moyo@example.test").exists()
    assert not Membership.objects.filter(user__email="rudo.moyo@example.test").exists()
    assert not Subscription.objects.filter(tenant__slug="new-registration-school").exists()


@pytest.mark.django_db
def test_registered_administrator_is_associated_only_with_new_tenant(client, tenant_a):
    client.force_login(User.objects.create_superuser("platform-scope@example.test", "unused"))
    submit_prior_steps(client)
    submit_creation(client)

    administrator = User.objects.get(email="rudo.moyo@example.test")
    memberships = Membership.objects.filter(user=administrator)
    assert memberships.count() == 1
    assert memberships.get().tenant.slug == "new-registration-school"
    assert memberships.get().tenant != tenant_a


@pytest.mark.django_db
def test_wizard_preserves_step_data_but_not_password(client):
    client.force_login(User.objects.create_superuser("platform-session@example.test", "unused"))
    submit_prior_steps(client)

    session_data = client.session["tenant_registration_wizard"]
    response = client.get(reverse(WIZARD_URL), {"step": 4})

    assert session_data["1"]["code"] == "new-registration-school"
    assert session_data["2"]["email"] == "rudo.moyo@example.test"
    assert "password" not in str(session_data).lower()
    assert response.status_code == 200
    assert b"Review and create" in response.content
