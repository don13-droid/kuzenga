from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.core.models import AuditEvent
from apps.tenancy.models import Membership, Role, Tenant

User = get_user_model()


def png_upload(name, color=(12, 34, 56)):
    image = Image.new("RGB", (8, 8), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/png")


def tenant_form_data(*, name="Admin Form School", slug="admin-form-school"):
    return {
        "name": name,
        "slug": slug,
        "status": Tenant.Status.ACTIVE,
        "timezone": "Africa/Harare",
        "default_currency": Tenant.Currency.USD,
        "country": "ZW",
        "school_email": "office@example.test",
        "school_primary_phone": "+263 4 111111",
        "school_alternative_phone": "+263 4 222222",
        "physical_address": "10 School Road",
        "postal_address": "PO Box 10",
        "website": "https://school.example.test",
    }


def administrator_form_data(*, name="Admin Person", email="admin-person@example.test", phone="+263 77 1111111"):
    return {
        "administrator_full_name": name,
        "administrator_email": email,
        "administrator_phone": phone,
    }


@pytest.fixture
def media_root(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def platform_user():
    return User.objects.create_superuser("tenant-editor@example.test", "Unused-password-1!")


@pytest.mark.django_db(transaction=True)
def test_superuser_can_create_tenant_with_school_contacts_and_logo(
    client, platform_user, media_root
):
    client.force_login(platform_user)

    response = client.post(
        reverse("admin:tenancy_tenant_add"),
        {**tenant_form_data(), "logo": png_upload("school-logo.png")},
    )

    assert response.status_code == 302
    tenant = Tenant.objects.get(slug="admin-form-school")
    assert tenant.school_email == "office@example.test"
    assert tenant.school_primary_phone == "+263 4 111111"
    assert tenant.school_alternative_phone == "+263 4 222222"
    assert tenant.physical_address == "10 School Road"
    assert tenant.postal_address == "PO Box 10"
    assert tenant.website == "https://school.example.test"
    assert tenant.logo.name.startswith("tenant-logos/")
    assert tenant.logo.storage.exists(tenant.logo.name)
    assert tenant.logo.path.startswith(str(media_root))


@pytest.mark.django_db(transaction=True)
def test_tenant_edit_replaces_and_removes_school_and_admin_images(
    client, tenant_a, admin_a, platform_user, media_root
):
    Membership.objects.filter(user=admin_a, tenant=tenant_a).update(role=Role.OWNER)
    admin_a.full_name = "Original Administrator"
    admin_a.phone = "+263 77 0000000"
    admin_a.save(update_fields=("full_name", "phone", "updated_at"))
    tenant_a.logo.save("initial-school.png", png_upload("initial-school.png"), save=True)
    admin_a.profile_image.save("initial-admin.png", png_upload("initial-admin.png"), save=True)
    initial_logo_name = tenant_a.logo.name
    initial_profile_name = admin_a.profile_image.name
    change_url = reverse("admin:tenancy_tenant_change", args=[tenant_a.pk])
    client.force_login(platform_user)

    edit_page = client.get(change_url)
    assert edit_page.status_code == 200
    assert tenant_a.logo.url.encode() in edit_page.content
    assert admin_a.profile_image.url.encode() in edit_page.content
    assert b"School Information and Contact Details" in edit_page.content
    assert b"Primary Administrator Details" in edit_page.content
    assert b"tenant-images.js" in edit_page.content

    replacement = client.post(
        change_url,
        {
            **tenant_form_data(name="Updated Admin Form School", slug=tenant_a.slug),
            **administrator_form_data(name="Updated Administrator", phone="+263 77 9999999"),
            "logo": png_upload("replacement-school.png", color=(90, 12, 12)),
            "administrator_profile_image": png_upload(
                "replacement-admin.png", color=(12, 90, 12)
            ),
        },
    )
    assert replacement.status_code == 302

    tenant_a.refresh_from_db()
    admin_a.refresh_from_db()
    replacement_logo_name = tenant_a.logo.name
    replacement_profile_name = admin_a.profile_image.name
    assert tenant_a.name == "Updated Admin Form School"
    assert tenant_a.school_primary_phone == "+263 4 111111"
    assert admin_a.full_name == "Updated Administrator"
    assert admin_a.phone == "+263 77 9999999"
    assert tenant_a.school_primary_phone != admin_a.phone
    assert tenant_a.logo.storage.exists(replacement_logo_name)
    assert admin_a.profile_image.storage.exists(replacement_profile_name)
    assert not tenant_a.logo.storage.exists(initial_logo_name)
    assert not admin_a.profile_image.storage.exists(initial_profile_name)
    tenant_change_event = AuditEvent.objects.filter(
        tenant=tenant_a, action="tenant.profile_updated"
    ).latest("created_at")
    administrator_event = AuditEvent.objects.filter(
        tenant=tenant_a, action="tenant.user_updated", target_user=admin_a
    ).latest("created_at")
    assert tenant_change_event.actor == platform_user
    assert tenant_change_event.changes["name"]["before"] == "School a"
    assert tenant_change_event.changes["school_primary_phone"] == "[REDACTED]"
    assert administrator_event.actor == platform_user
    assert "administrator_email" in administrator_event.changes["profile_fields_updated"]

    removed = client.post(
        change_url,
        {
            **tenant_form_data(name=tenant_a.name, slug=tenant_a.slug),
            **administrator_form_data(
                name=admin_a.full_name, email=admin_a.email, phone=admin_a.phone
            ),
            "logo-clear": "on",
            "administrator_profile_image-clear": "on",
        },
    )
    assert removed.status_code == 302
    tenant_a.refresh_from_db()
    admin_a.refresh_from_db()
    assert not tenant_a.logo
    assert not admin_a.profile_image
    assert not tenant_a.logo.storage.exists(replacement_logo_name)
    assert not admin_a.profile_image.storage.exists(replacement_profile_name)


@pytest.mark.django_db
def test_tenant_admin_keeps_optional_profile_fields_blank(client, tenant_a, platform_user):
    client.force_login(platform_user)

    response = client.get(reverse("admin:tenancy_tenant_change", args=[tenant_a.pk]))

    assert response.status_code == 200
    assert tenant_a.school_email == ""
    assert not tenant_a.logo
    assert b"No active owner or administrator is assigned" in response.content


@pytest.mark.django_db
def test_tenant_admin_rejects_invalid_image_content(client, tenant_a, admin_a, platform_user):
    client.force_login(platform_user)
    Membership.objects.filter(user=admin_a, tenant=tenant_a).update(role=Role.OWNER)

    response = client.post(
        reverse("admin:tenancy_tenant_change", args=[tenant_a.pk]),
        {
            **tenant_form_data(name="Must Not Save", slug=tenant_a.slug),
            **administrator_form_data(email=admin_a.email),
            "logo": SimpleUploadedFile(
                "not-really-an-image.png", b"not an image", content_type="image/png"
            ),
        },
    )

    assert response.status_code == 200
    assert b"Upload a valid image" in response.content
    tenant_a.refresh_from_db()
    assert tenant_a.name != "Must Not Save"


@pytest.mark.django_db
def test_only_platform_superusers_can_edit_tenant_and_primary_admin(client, tenant_a, admin_a):
    staff_user = User.objects.create_user(
        "staff-editor@example.test", "Unused-password-1!", is_staff=True
    )
    client.force_login(staff_user)

    response = client.get(reverse("admin:tenancy_tenant_change", args=[tenant_a.pk]))

    assert response.status_code == 403
    client.force_login(admin_a)
    assert client.get(reverse("admin:tenancy_tenant_change", args=[tenant_a.pk])).status_code in (302, 403)
