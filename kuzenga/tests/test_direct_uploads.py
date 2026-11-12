import hashlib
import io
import json
import time
from unittest.mock import Mock, patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.context import tenant_context
from apps.core.direct_uploads import PREFIX, TTL
from apps.core.models import AuditEvent
from apps.students.models import StudentDocument
from apps.tenancy.models import Membership

from .test_media_and_navigation import png
from .test_student_management import make_student


@pytest.fixture
def storage(settings, tmp_path):
    settings.DIRECT_UPLOADS_ENABLED = True
    settings.S3_BUCKET_NAME = "private-test-bucket"
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"
    settings.MEDIA_ROOT = tmp_path / "media"
    sdk = Mock()
    sdk.generate_presigned_url.return_value = "https://objects.example.invalid/private?signature=test-only"
    with patch("apps.core.direct_uploads.client", return_value=sdk):
        yield sdk


def issue(client, destination, content, **changes):
    data = {"target": destination, "field": "file", "name": "record.pdf", "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), **changes}
    return client.post(reverse("direct-upload-grant"), json.dumps(data), content_type="application/json")


def complete(client, storage, target, content, ticket):
    storage.get_object.return_value = {"Body": io.BytesIO(content), "ContentLength": len(content)}
    return client.post(target, {"action": "document", "title": "Private record", PREFIX + "file": ticket})


def test_large_pdf_uses_small_form_request_and_existing_audit(client, storage, tenant_a, admin_a):
    student = make_student(tenant_a)
    target = reverse("students:detail", args=[student.pk])
    content = b"%PDF-1.4\n" + b" " * (5 * 1024 * 1024) + b"\n%%EOF"
    client.force_login(admin_a)
    response = issue(client, target, content)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    grant = response.json()
    args = storage.generate_presigned_url.call_args.kwargs
    assert args["ExpiresIn"] == TTL
    assert args["Params"]["ContentLength"] == len(content)
    assert args["Params"]["Key"].startswith(f"staging-uploads/{tenant_a.pk}/")
    response = complete(client, storage, target, content, grant["ticket"])
    assert response.status_code == 302
    assert int(response.wsgi_request.META["CONTENT_LENGTH"]) < 10000
    with tenant_context(tenant_a):
        document = StudentDocument.objects.get(student=student)
        with document.file.open("rb") as stream:
            assert stream.read() == content
        assert AuditEvent.objects.filter(action__contains="document").exists()
        with pytest.raises(ValueError):
            _ = document.file.url


@pytest.mark.parametrize("changes", [
    {"size": 11 * 1024 * 1024}, {"size": 0}, {"size": True}, {"name": "record.exe"},
    {"name": "../record.pdf"}, {"sha256": "invalid"}, {"field": "logo"}, {"target": "https://other.invalid/"},
])
def test_grants_reject_unsafe_metadata(client, storage, tenant_a, admin_a, changes):
    student = make_student(tenant_a)
    client.force_login(admin_a)
    response = issue(client, reverse("students:detail", args=[student.pk]), b"%PDF-1.4\n%%EOF", **changes)
    assert response.status_code in {400, 403}
    storage.generate_presigned_url.assert_not_called()


def test_grants_deny_other_school_and_missing_permission(client, storage, tenant_b, admin_a, teacher_a):
    other = make_student(tenant_b)
    target = reverse("students:detail", args=[other.pk])
    client.force_login(admin_a)
    assert issue(client, target, b"test").status_code == 404
    client.force_login(teacher_a)
    assert issue(client, target, b"test").status_code == 403
    client.logout()
    assert issue(client, target, b"test").status_code == 302
    storage.generate_presigned_url.assert_not_called()


@pytest.mark.parametrize("mode", ["tampered", "expired", "changed", "invalid-content", "wrong-size", "other-user", "revoked"])
def test_consumption_fails_closed(client, storage, tenant_a, admin_a, admin_b, mode):
    student = make_student(tenant_a)
    target = reverse("students:detail", args=[student.pk])
    content = b"%PDF-1.4\n%%EOF" if mode != "invalid-content" else b"not-a-document"
    client.force_login(admin_a)
    ticket = issue(client, target, content).json()["ticket"]
    if mode == "tampered":
        ticket += "changed"
    if mode == "changed":
        content = content.replace(b"1.4", b"1.5")
    if mode == "wrong-size":
        content += b" "
    if mode == "other-user":
        client.force_login(admin_b)
    if mode == "revoked":
        Membership.objects.filter(user=admin_a, tenant=tenant_a).update(status="suspended")
    clock = time.time() + TTL + 5 if mode == "expired" else time.time()
    with patch("django.core.signing.time.time", return_value=clock):
        response = complete(client, storage, target, content, ticket)
    assert response.status_code in {400, 403}
    with tenant_context(tenant_a):
        assert not StudentDocument.objects.filter(student=student).exists()


def test_grant_and_completion_require_csrf(storage, tenant_a, admin_a):
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(admin_a)
    target = reverse("students:detail", args=[make_student(tenant_a).pk])
    assert issue(browser, target, b"%PDF-1.4\n%%EOF").status_code == 403
    assert browser.post(target, {PREFIX + "file": "forged"}).status_code == 403
    storage.generate_presigned_url.assert_not_called()
    storage.get_object.assert_not_called()


def test_student_image_uses_existing_form_and_protected_media(client, storage, tenant_a, admin_a):
    student = make_student(tenant_a)
    target = reverse("students:edit", args=[student.pk])
    content = png().read()
    client.force_login(admin_a)
    response = issue(client, target, content, field="profile_image", name="portrait.png")
    assert response.status_code == 200
    storage.get_object.return_value = {"Body": io.BytesIO(content), "ContentLength": len(content)}
    response = client.post(target, {"first_name": student.first_name, "last_name": student.last_name,
                                    PREFIX + "profile_image": response.json()["ticket"]})
    assert response.status_code == 302
    student.refresh_from_db()
    assert student.profile_image.url.startswith("/media/student-images/")
    response = client.get(student.profile_image.url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert b"".join(response.streaming_content) == content


def test_ticket_cannot_be_reused_for_a_different_record(client, storage, tenant_a, admin_a):
    student = make_student(tenant_a)
    with tenant_context(tenant_a):
        from apps.students.models import Student

        other = Student.objects.create(first_name="Other", last_name="Student", admission_number="OTHER")
    client.force_login(admin_a)
    content = b"%PDF-1.4\n%%EOF"
    ticket = issue(client, reverse("students:detail", args=[student.pk]), content).json()["ticket"]
    response = complete(client, storage, reverse("students:detail", args=[other.pk]), content, ticket)
    assert response.status_code == 403
    storage.get_object.assert_not_called()


def test_nonempty_staging_database_is_rejected_before_migrations():
    from django.core.management import CommandError

    from scripts.migrate_preview import require_empty_database

    connection = Mock()
    connection.cursor.return_value.__enter__ = Mock(return_value=Mock())
    connection.cursor.return_value.__exit__ = Mock(return_value=False)
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = [True]
    with pytest.raises(CommandError, match="not empty"):
        require_empty_database(connection)
