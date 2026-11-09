from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.urls import reverse
from PIL import Image

pytestmark = pytest.mark.django_db


def png(name="photo.png"):
    stream = BytesIO()
    Image.new("RGB", (12, 12), "navy").save(stream, "PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


def test_logo_is_stored_rendered_and_retrievable(client, tenant_a, admin_a, media):
    tenant_a.logo = png()
    tenant_a.save()
    assert tenant_a.logo.storage.exists(tenant_a.logo.name)
    assert tenant_a.logo.url.startswith("/media/tenant-logos/")
    client.force_login(admin_a)
    response = client.get(reverse("dashboard"))
    assert tenant_a.logo.url.encode() in response.content
    image = client.get(tenant_a.logo.url)
    assert image.status_code == 200
    assert image["Content-Type"] == "image/png"
    assert image["Cache-Control"] == "private, no-store"
    assert b"".join(image.streaming_content).startswith(b"\x89PNG")


def test_platform_logo_directory_overview_and_staff_rendering(client, tenant_a, admin_a, media):
    tenant_a.logo = png("school.png")
    tenant_a.save()
    admin_a.profile_image = png()
    admin_a.save()
    platform = get_user_model().objects.create_superuser("image-platform@example.test", "unused-password")
    client.force_login(platform)
    for route, args in [("superuser:tenant-directory", []), ("superuser:tenant-overview", [tenant_a.pk])]:
        assert tenant_a.logo.url.encode() in client.get(reverse(route, args=args)).content
    assert client.get(tenant_a.logo.url).status_code == 200
    membership = admin_a.memberships.get(tenant=tenant_a)
    for route, args in [("superuser:tenant-users", [tenant_a.pk]),
                        ("superuser:tenant-user-profile", [tenant_a.pk, membership.pk])]:
        assert admin_a.profile_image.url.encode() in client.get(reverse(route, args=args)).content
    assert client.get(admin_a.profile_image.url).status_code == 200


def test_images_deny_anonymous_and_other_tenant(client, tenant_a, tenant_b, admin_a, admin_b, media):
    tenant_b.logo = png()
    tenant_b.save()
    admin_b.profile_image = png()
    admin_b.save()
    assert client.get(tenant_b.logo.url).status_code == 302
    client.force_login(admin_a)
    assert client.get(tenant_b.logo.url).status_code == 404
    assert client.get(admin_b.profile_image.url).status_code == 404
    assert client.get("/media/private-documents/secret.pdf").status_code == 404
    assert client.get("/media/tenant-logos/unknown.png").status_code == 404


def test_missing_file_uses_placeholder_without_changing_reference(client, tenant_a, admin_a, media):
    tenant_a.logo = "tenant-logos/missing.png"
    tenant_a.save()
    client.force_login(admin_a)
    assert client.get(tenant_a.logo.url).status_code == 404
    html = Template('{% load images %}{% avatar logo label %}').render(Context({"logo": tenant_a.logo, "label": "School"}))
    assert "<img" not in html and 'aria-label="School"' in html
    tenant_a.refresh_from_db()
    assert tenant_a.logo.name == "tenant-logos/missing.png"


def test_shared_shells_render_independent_sidebar_and_styles(client, tenant_a, admin_a):
    client.force_login(admin_a)
    html = client.get(reverse("students:list")).content.decode()
    assert 'class="school-layout md:flex"' in html
    assert 'class="school-sidebar' in html and 'class="school-content' in html
    assert 'css/layout.css' in html and 'aria-label="School navigation"' in html
    platform = get_user_model().objects.create_superuser("layout-platform@example.test", "unused-password")
    client.force_login(platform)
    html = client.get(reverse("superuser:tenant-directory")).content.decode()
    assert 'class="platform-content' in html and 'css/layout.css' in html
