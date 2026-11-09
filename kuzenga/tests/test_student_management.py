from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.core.context import tenant_context
from apps.core.exceptions import TenantContextMissing, TenantMismatch
from apps.core.models import AuditEvent
from apps.students import services
from apps.students.models import Guardian, Student, StudentDocument, StudentEnrolment, StudentGuardian
from apps.students.validators import MAX_DOCUMENT_BYTES, validate_student_document

from .conftest import make_class
from .test_media_and_navigation import png

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def uploads(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"


def pdf(name="record.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n", content_type="application/pdf")


def make_student(tenant, **data):
    with tenant_context(tenant):
        return services.create_student(first_name="Tariro", last_name="Moyo", **data)


def detail(student):
    return reverse("students:detail", args=[student.pk])


def test_registration_with_guardian_class_image_and_unique_number(client, tenant_a, admin_a):
    group = make_class(tenant_a)
    client.force_login(admin_a)
    data = {
        "first_name": "Rudo", "last_name": "Dube", "date_of_birth": "2012-04-03", "gender": "F",
        "class_group": group.pk, "profile_image": png(), "guardian-first_name": "Contact",
        "guardian-last_name": "Dube", "guardian-phone": "+263770000000",
        "guardian-relationship": "Parent", "guardian-is_primary": "on", "guardian-is_emergency": "on",
    }
    response = client.post(reverse("students:create"), data)
    assert response.status_code == 302
    with tenant_context(tenant_a):
        student = Student.objects.get()
        link = StudentGuardian.objects.get(student=student)
        assert student.admission_number and student.profile_image.storage.exists(student.profile_image.name)
        assert link.is_primary and link.is_emergency and link.guardian.phone
        assert StudentEnrolment.objects.get(student=student).class_group == group
        image_url = student.profile_image.url
    html = client.get(detail(student)).content
    assert image_url.encode() in html and b"emergency contact" in html
    assert client.get(image_url).status_code == 200
    assert not AuditEvent.objects.filter(object_id=str(student.pk)).filter(metadata__icontains="Rudo").exists()


def test_registration_guardian_failure_creates_nothing(client, tenant_a, admin_a):
    client.force_login(admin_a)
    response = client.post(reverse("students:create"), {
        "first_name": "New", "last_name": "Student", "guardian-is_emergency": "on",
    })
    assert response.status_code == 200
    assert response.context["guardian_form"].errors
    with tenant_context(tenant_a):
        assert not Student.objects.exists() and not Guardian.objects.exists()


def test_registration_rollback_if_guardian_service_rejects(tenant_a, admin_a):
    with tenant_context(tenant_a), pytest.raises(ValidationError):
        services.create_student(first_name="New", last_name="Student", actor=admin_a,
                                guardian_data={"first_name": "G", "last_name": "One", "is_emergency": True})
    with tenant_context(tenant_a):
        assert not Student.objects.exists() and not Guardian.objects.exists()


def test_admission_number_uniqueness_and_generated_collision_skip(client, tenant_a, tenant_b, admin_a):
    number = f"{timezone.localdate().year % 100:02d}0001"
    make_student(tenant_a, admission_number=number)
    make_student(tenant_b, admission_number=number)
    generated = make_student(tenant_a)
    assert generated.admission_number != number
    client.force_login(admin_a)
    response = client.post(reverse("students:create"), {"first_name": "Other", "last_name": "One", "admission_number": number})
    assert response.status_code == 200 and response.context["form"].errors
    with tenant_context(tenant_a), pytest.raises(ValidationError):
        services.create_student(first_name="Other", last_name="One", admission_number=number)


def test_edit_preserves_admission_number_and_redacts_audit(client, tenant_a, admin_a):
    student = make_student(tenant_a, date_of_birth=timezone.localdate() - timedelta(days=5000))
    client.force_login(admin_a)
    response = client.post(reverse("students:edit", args=[student.pk]), {
        "first_name": "Changed", "last_name": "Moyo", "preferred_name": "Private name",
        "date_of_birth": student.date_of_birth.isoformat(), "admission_number": "ATTACK", "gender": "F",
    })
    assert response.status_code == 302
    student.refresh_from_db()
    assert student.first_name == "Changed" and student.admission_number != "ATTACK"
    event = AuditEvent.objects.get(action="student.updated", object_id=str(student.pk))
    assert event.changes["first_name"] == "[REDACTED]"
    assert "Private name" not in str(event.changes)
    # Unchanged name and birth date on edit must not be mistaken for a duplicate record.
    response = client.post(reverse("students:edit", args=[student.pk]), {
        "first_name": "Changed", "last_name": "Moyo", "date_of_birth": student.date_of_birth.isoformat(),
    })
    assert response.status_code == 302


def test_future_birthdate_rejected(client, tenant_a, admin_a):
    client.force_login(admin_a)
    response = client.post(reverse("students:create"), {
        "first_name": "Future", "last_name": "Child", "date_of_birth": timezone.localdate() + timedelta(days=1),
    })
    assert "date_of_birth" in response.context["form"].errors


def test_student_permissions_and_cross_tenant_urls(client, tenant_a, tenant_b, admin_a, teacher_a):
    student = make_student(tenant_a)
    other = make_student(tenant_b)
    client.force_login(teacher_a)
    assert client.get(detail(student)).status_code == 200
    assert client.get(reverse("students:edit", args=[student.pk])).status_code == 403
    assert client.post(detail(student), {"action": "status", "status": "withdrawn", "reason": "test"}).status_code == 403
    with tenant_context(tenant_a), pytest.raises(PermissionDenied):
        services.change_student_status(student, status="withdrawn", reason="test", actor=teacher_a)
    client.force_login(admin_a)
    assert client.get(detail(other)).status_code == 404
    assert client.get(reverse("students:edit", args=[other.pk])).status_code == 404
    assert client.post(reverse("students:edit", args=[other.pk]), {"first_name": "Attack"}).status_code == 404


def test_directory_full_name_admission_filters_and_pagination(client, tenant_a, admin_a):
    group = make_class(tenant_a)
    student = make_student(tenant_a, class_group=group)
    with tenant_context(tenant_a):
        for index in range(26):
            services.create_student(first_name="Other", last_name=f"Learner {index}")
    client.force_login(admin_a)
    for query in ({"q": "Tariro Moyo"}, {"q": student.admission_number}, {"class_group": group.pk},
                  {"academic_year": group.academic_year_id}, {"class_group": group.pk, "academic_year": group.academic_year_id}):
        response = client.get(reverse("students:list"), query)
        assert [record.pk for record in response.context["page"]] == [student.pk]
    response = client.get(reverse("students:list"), {"status": "active", "page": 2})
    assert len(response.context["page"]) == 2
    assert b"status=active" in response.content


def test_directory_rejects_foreign_and_invalid_filters(client, tenant_a, tenant_b, admin_a):
    make_student(tenant_a)
    other = make_class(tenant_b)
    client.force_login(admin_a)
    for query in ({"class_group": other.pk}, {"academic_year": other.academic_year_id}, {"class_group": "invalid"}, {"status": "nonsense"}):
        response = client.get(reverse("students:list"), query)
        assert response.context["filters"].errors
        assert len(response.context["page"]) == 0
        assert str(other.pk).encode() not in response.content


def test_guardian_reuse_primary_emergency_and_tenant_boundaries(client, tenant_a, tenant_b, admin_a):
    first = make_student(tenant_a)
    second = make_student(tenant_a)
    with tenant_context(tenant_a):
        guardian = Guardian.objects.create(first_name="Parent", last_name="One", phone="+263770000001")
    with tenant_context(tenant_b):
        foreign = Guardian.objects.create(first_name="Other", last_name="Parent")
    client.force_login(admin_a)
    for student in (first, second):
        response = client.post(detail(student), {"action": "guardian", "guardian": guardian.pk,
                                                 "relationship": "Parent", "is_primary": "on", "is_emergency": "on"})
        assert response.status_code == 302
    with tenant_context(tenant_a):
        assert Guardian.objects.count() == 1
        assert StudentGuardian.objects.filter(guardian=guardian).count() == 2
        with pytest.raises(TenantMismatch):
            services.add_guardian(first, guardian=foreign, actor=admin_a)
    response = client.post(detail(first), {"action": "guardian", "guardian": foreign.pk})
    assert response.context["guardian_form"].errors


@pytest.mark.parametrize("status", ["transferred", "withdrawn", "graduated", "archived", "suspended"])
def test_status_changes_and_reactivation_preserve_history(client, tenant_a, admin_a, status):
    group = make_class(tenant_a)
    student = make_student(tenant_a)
    with tenant_context(tenant_a):
        enrolment = services.enrol_student(student, group, effective_from=timezone.localdate() - timedelta(days=20))
    client.force_login(admin_a)
    response = client.post(detail(student), {"action": "status", "status": status, "reason": "Approved change"})
    assert response.status_code == 302
    student.refresh_from_db()
    enrolment.refresh_from_db()
    assert student.status == status
    if status != "suspended":
        assert enrolment.effective_to == timezone.localdate()
    assert client.post(detail(student), {"action": "status", "status": "active", "reason": "Return"}).status_code == 302
    with tenant_context(tenant_a):
        assert StudentEnrolment.objects.filter(student=student).count() == 1
    assert AuditEvent.objects.filter(action="student.status_changed", object_id=str(student.pk)).count() == 2


def test_invalid_status_and_reason_rejected_without_change(client, tenant_a, admin_a):
    student = make_student(tenant_a)
    client.force_login(admin_a)
    for data in ({"status": "unknown", "reason": "test"}, {"status": "withdrawn", "reason": ""}):
        response = client.post(detail(student), {"action": "status", **data})
        assert response.context["status_form"].errors
    student.refresh_from_db()
    assert student.status == "active"


def test_class_assignment_checks_before_mutation_and_keeps_history(client, tenant_a, tenant_b, admin_a):
    group = make_class(tenant_a)
    other_group = make_class(tenant_b)
    student = make_student(tenant_a)
    with tenant_context(tenant_a):
        enrolment = services.enrol_student(student, group, effective_from=timezone.localdate() - timedelta(days=10))
        with pytest.raises(TenantMismatch):
            services.enrol_student(student, other_group, actor=admin_a)
        enrolment.refresh_from_db()
        assert enrolment.effective_to is None
    client.force_login(admin_a)
    assert client.post(detail(student), {"action": "enrol", "class_group": other_group.pk}).context["enrol_form"].errors
    with pytest.raises(TenantContextMissing):
        services.enrol_student(student, group)


def test_private_document_upload_download_and_access_controls(client, tenant_a, tenant_b, admin_a, admin_b, teacher_a, settings):
    student = make_student(tenant_a)
    other = make_student(tenant_b)
    client.force_login(admin_a)
    response = client.post(detail(student), {"action": "document", "title": "Enrolment record", "file": pdf()})
    assert response.status_code == 302
    with tenant_context(tenant_a):
        document = StudentDocument.objects.get(student=student)
        assert document.file.storage.exists(document.file.name)
        assert str(settings.PRIVATE_MEDIA_ROOT) in document.file.path
        with pytest.raises(ValueError):
            _ = document.file.url
    url = reverse("students:document-download", args=[student.pk, document.pk])
    response = client.get(url)
    assert response.status_code == 200 and response["Content-Disposition"].startswith("attachment;")
    assert response["Cache-Control"] == "private, no-store"
    assert b"".join(response.streaming_content).startswith(b"%PDF-")
    assert client.get(reverse("students:document-download", args=[other.pk, document.pk])).status_code == 404
    assert client.get("/media/" + document.file.name).status_code == 404
    client.force_login(teacher_a)
    assert client.get(url).status_code == 403
    assert b"Enrolment record" not in client.get(detail(student)).content
    client.force_login(admin_b)
    assert client.get(url).status_code == 404
    client.logout()
    assert client.get(url).status_code == 302


@pytest.mark.parametrize("name,content", [("record.exe", b"MZ"), ("fake.pdf", b"not a pdf"),
                                          ("fake.png", b"not an image"), ("empty.pdf", b"")])
def test_document_type_content_validation(client, tenant_a, admin_a, name, content):
    student = make_student(tenant_a)
    client.force_login(admin_a)
    response = client.post(detail(student), {"action": "document", "title": "Invalid",
                                             "file": SimpleUploadedFile(name, content)})
    assert response.context["document_form"].errors
    with tenant_context(tenant_a):
        assert not StudentDocument.objects.exists()


def test_document_size_limit():
    upload = pdf()
    upload.size = MAX_DOCUMENT_BYTES + 1
    with pytest.raises(ValidationError):
        validate_student_document(upload)


def test_document_model_rejects_foreign_student(tenant_a, tenant_b, admin_a):
    other = make_student(tenant_b)
    with tenant_context(tenant_a), pytest.raises(TenantMismatch):
        services.upload_document(other, title="Invalid", file=pdf(), actor=admin_a)


def test_student_photo_denies_other_tenant(client, tenant_a, tenant_b, admin_a, admin_b):
    student = make_student(tenant_a, profile_image=png())
    client.force_login(admin_a)
    assert client.get(student.profile_image.url).status_code == 200
    client.force_login(admin_b)
    assert client.get(student.profile_image.url).status_code == 404


def test_activity_is_tenant_scoped(client, tenant_a, tenant_b, admin_a):
    student = make_student(tenant_a)
    AuditEvent.objects.create(tenant=tenant_b, action="student.updated", description="FOREIGN SECRET",
                              object_type="Student", object_id=str(student.pk))
    client.force_login(admin_a)
    response = client.get(detail(student))
    assert b"Student created" in response.content
    assert b"FOREIGN SECRET" not in response.content
