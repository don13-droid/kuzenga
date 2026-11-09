from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.admissions import services
from apps.admissions.models import ApplicationDocument, ApplicationNote, StudentApplication
from apps.core.context import tenant_context
from apps.core.models import AuditEvent
from apps.students.models import (
    AdmissionSequence,
    Guardian,
    Student,
    StudentDocument,
    StudentEnrolment,
    StudentGuardian,
)
from apps.tenancy.models import Entitlement, Membership, Role

from .conftest import make_class, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def private_storage(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"


def applicant_data(group=None, **extra):
    result = dict(first_name="Tariro", last_name="Dube", guardian_first_name="Parent",
                  guardian_last_name="Dube", guardian_phone="+263770000001", guardian_relationship="Parent")
    if group:
        result.update(intended_year=group.academic_year, intended_grade=group.grade, intended_class=group)
    result.update(extra)
    return result


def application(tenant, actor, *, group=None, submit=True, **extra):
    with tenant_context(tenant):
        return services.create_application(actor=actor, data=applicant_data(group, **extra), submit=submit)


def advance(app, actor, target):
    return services.transition_application(app, actor=actor, target=target, reason="Recorded decision")


def accepted(tenant, actor, group):
    app = application(tenant, actor, group=group)
    with tenant_context(tenant):
        return advance(advance(app, actor, "under_review"), actor, "accepted")


def detail(app):
    return reverse("admissions:detail", args=[app.pk])


def pdf():
    return SimpleUploadedFile("certificate.pdf", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n", content_type="application/pdf")


def test_create_draft_and_submit_with_class_inference_and_audit(client, tenant_a, admin_a):
    group = make_class(tenant_a)
    client.force_login(admin_a)
    response = client.post(reverse("admissions:create"), {"first_name": "Tariro", "last_name": "Dube",
        "document-kind": "birth_certificate"})  # Browser sends the optional select even without a file.
    assert response.status_code == 302
    with tenant_context(tenant_a):
        draft = StudentApplication.objects.get()
        assert draft.status == "draft" and draft.reference.startswith("ADM-")
    response = client.post(reverse("admissions:create"), {"first_name": "Submitted", "last_name": "Applicant",
        "intended_class": group.pk, "guardian_first_name": "Parent", "guardian_last_name": "One",
        "guardian_phone": "+263770000001", "application_date": timezone.localdate(), "submit": "yes"})
    assert response.status_code == 302
    with tenant_context(tenant_a):
        app = StudentApplication.objects.get(first_name="Submitted")
        assert app.status == "submitted" and app.intended_year == group.academic_year and app.intended_grade == group.grade
        assert len(list(services.application_history(app, actor=admin_a))) == 2
    event = AuditEvent.objects.get(action="admissions.created", object_id=str(draft.pk))
    assert event.actor == admin_a and event.tenant == tenant_a
    assert "Tariro" not in str(event.metadata)


def test_submission_requires_placement_and_contact(client, tenant_a, admin_a):
    client.force_login(admin_a)
    response = client.post(reverse("admissions:create"), {"first_name": "Incomplete", "last_name": "Applicant",
        "application_date": timezone.localdate(), "submit": "yes"})
    assert response.status_code == 200 and response.context["form"].errors
    with tenant_context(tenant_a):
        assert not StudentApplication.objects.exists()
        app = services.create_application(actor=admin_a, data=applicant_data())
        with pytest.raises(ValidationError):
            advance(app, admin_a, "submitted")
        app.refresh_from_db()
        assert app.status == "draft"


@pytest.mark.parametrize("target", ["accepted", "rejected", "waitlisted"])
def test_decision_path_and_required_reason(tenant_a, admin_a, target):
    app = application(tenant_a, admin_a, group=make_class(tenant_a))
    with tenant_context(tenant_a):
        app = advance(app, admin_a, "under_review")
        with pytest.raises(ValidationError):
            services.transition_application(app, actor=admin_a, target=target)
        app = advance(app, admin_a, target)
        assert app.status == target
        event = AuditEvent.objects.get(action=f"admissions.{target}", object_id=str(app.pk))
        assert event.changes["status"] == {"before": "under_review", "after": target}
        assert event.actor == admin_a and event.created_at
        assert ApplicationNote.objects.get(audit_event=event).body == "Recorded decision"
        assert "Recorded decision" not in str(event.metadata)


@pytest.mark.parametrize("target", ["under_review", "accepted"])
def test_waitlist_can_return_to_review_or_acceptance(tenant_a, admin_a, target):
    app = application(tenant_a, admin_a, group=make_class(tenant_a))
    with tenant_context(tenant_a):
        app = advance(advance(app, admin_a, "under_review"), admin_a, "waitlisted")
        app = advance(app, admin_a, target)
        assert app.status == target
        assert AuditEvent.objects.filter(object_id=str(app.pk), action="admissions.waitlisted").count() == 1


@pytest.mark.parametrize("source,target", [
    ("draft", "accepted"), ("submitted", "accepted"), ("submitted", "rejected"),
    ("under_review", "draft"), ("accepted", "rejected"), ("accepted", "enrolled"),
    ("rejected", "under_review"), ("waitlisted", "submitted"), ("waitlisted", "rejected"),
])
def test_invalid_transitions_never_rewrite_history(tenant_a, admin_a, source, target):
    app = application(tenant_a, admin_a, group=make_class(tenant_a), submit=source != "draft")
    with tenant_context(tenant_a):
        if source in ("under_review", "accepted", "rejected", "waitlisted"):
            app = advance(app, admin_a, "under_review")
        if source in ("accepted", "rejected", "waitlisted"):
            app = advance(app, admin_a, source)
        count = AuditEvent.objects.count()
        with pytest.raises(ValidationError):
            advance(app, admin_a, target)
        app.refresh_from_db()
        assert app.status == source and AuditEvent.objects.count() == count


def test_stale_decisions_and_edits_are_rejected(tenant_a, admin_a):
    app = application(tenant_a, admin_a, group=make_class(tenant_a))
    old_version = app.updated_at
    with tenant_context(tenant_a):
        advance(app, admin_a, "under_review")
        with pytest.raises(ValidationError):
            advance(app, admin_a, "under_review")
        with pytest.raises(ValidationError):
            services.update_application(app, actor=admin_a, data={"first_name": "Changed"}, expected_updated_at=old_version, reason="Correction")


def test_edit_requires_reason_and_redacts_changes(client, tenant_a, admin_a):
    app = application(tenant_a, admin_a, group=make_class(tenant_a))
    client.force_login(admin_a)
    url = reverse("admissions:edit", args=[app.pk])
    form = client.get(url).context["form"]
    data = {key: value.pk if hasattr(value, "pk") else value for key, value in applicant_data(app.intended_class).items()}
    data.update(application_date=app.application_date, expected_updated_at=app.updated_at.isoformat(), first_name="Corrected")
    assert 'type="hidden"' in str(form["expected_updated_at"])
    assert client.post(url, data).context["form"].errors
    data["reason"] = "Corrected a transcription error"
    assert client.post(url, data).status_code == 302
    app.refresh_from_db()
    assert app.first_name == "Corrected"
    event = AuditEvent.objects.get(action="admissions.updated", object_id=str(app.pk))
    assert event.changes["first_name"] == "[REDACTED]"
    assert "Corrected a transcription error" not in str(event.metadata)


def test_accepted_application_is_read_only(client, tenant_a, admin_a):
    app = accepted(tenant_a, admin_a, make_class(tenant_a))
    client.force_login(admin_a)
    assert client.get(reverse("admissions:edit", args=[app.pk])).status_code == 403
    with tenant_context(tenant_a), pytest.raises(ValidationError):
        services.update_application(app, actor=admin_a, data={"first_name": "Changed"}, expected_updated_at=app.updated_at, reason="Change")


def test_enrolment_reuses_student_services_guardian_and_is_idempotent(tenant_a, admin_a):
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        guardian = Guardian.objects.create(first_name="Parent", last_name="Existing", phone="+263770000001")
        app = services.create_application(actor=admin_a, data=applicant_data(group, guardian=guardian), submit=True)
        app = advance(advance(app, admin_a, "under_review"), admin_a, "accepted")
        student = services.enrol_application(app, actor=admin_a, class_group=group)
        again = services.enrol_application(app, actor=admin_a, class_group=group)
        assert again == student
        app.refresh_from_db()
        assert app.student == student and app.status == "enrolled"
        assert student.tenant == tenant_a and student.admission_number
        assert Guardian.objects.count() == 1 and Student.objects.count() == 1
        assert StudentGuardian.objects.get(student=student).guardian == guardian
        enrolment = StudentEnrolment.objects.get(student=student)
        assert enrolment.class_group == group and enrolment.class_group.academic_year == group.academic_year
        assert AuditEvent.objects.filter(action="admissions.enrolled", object_id=str(app.pk)).count() == 1


def test_enrolment_shares_private_document_without_copying_files(client, tenant_a, admin_a, settings):
    group = make_class(tenant_a)
    app = application(tenant_a, admin_a, group=group)
    with tenant_context(tenant_a):
        original = services.upload_document(app, actor=admin_a, kind="birth_certificate", title="Certificate", file=pdf())
        app.refresh_from_db()
        app = advance(advance(app, admin_a, "under_review"), admin_a, "accepted")
        before = list(settings.PRIVATE_MEDIA_ROOT.rglob("*.pdf"))
        student = services.enrol_application(app, actor=admin_a, class_group=group)
        linked = StudentDocument.objects.get(student=student)
        assert linked.file.name == original.file.name
        assert list(settings.PRIVATE_MEDIA_ROOT.rglob("*.pdf")) == before
        assert original.file.storage.exists(original.file.name)
    client.force_login(admin_a)
    response = client.get(reverse("students:document-download", args=[student.pk, linked.pk]))
    assert response.status_code == 200
    assert b"".join(response.streaming_content).startswith(b"%PDF-")


def test_missing_document_rolls_back_students_guardians_sequence_and_audit(tenant_a, admin_a):
    group = make_class(tenant_a)
    app = application(tenant_a, admin_a, group=group)
    with tenant_context(tenant_a):
        ApplicationDocument.objects.create(application=app, tenant=tenant_a, kind="other", title="Missing", file="admission-documents/missing.pdf")
        app = advance(advance(app, admin_a, "under_review"), admin_a, "accepted")
        before = AuditEvent.objects.count()
        with pytest.raises(ValidationError):
            services.enrol_application(app, actor=admin_a, class_group=group)
        assert not Student.objects.exists() and not Guardian.objects.exists() and not AdmissionSequence.objects.exists()
        assert AuditEvent.objects.count() == before
        app.refresh_from_db()
        assert app.status == "accepted" and app.student_id is None


def test_student_service_failure_rolls_back_whole_enrolment(tenant_a, admin_a, monkeypatch):
    group = make_class(tenant_a)
    app = accepted(tenant_a, admin_a, group)
    def fail(*args, **kwargs):
        raise ValidationError("Class assignment failed")
    monkeypatch.setattr("apps.admissions.services.student_services.enrol_student", fail)
    with tenant_context(tenant_a), pytest.raises(ValidationError):
        services.enrol_application(app, actor=admin_a, class_group=group)
    with tenant_context(tenant_a):
        assert not Student.objects.exists() and not Guardian.objects.exists()
        assert not StudentGuardian.objects.exists() and not AdmissionSequence.objects.exists()


def test_enrolment_requires_acceptance_matching_year_grade_class_and_dates(tenant_a, tenant_b, admin_a):
    group = make_class(tenant_a)
    foreign = make_class(tenant_b)
    app = application(tenant_a, admin_a, group=group)
    with tenant_context(tenant_a):
        with pytest.raises(ValidationError):
            services.enrol_application(app, actor=admin_a, class_group=group)
        app = advance(advance(app, admin_a, "under_review"), admin_a, "accepted")
        with pytest.raises(ValidationError):
            services.enrol_application(app, actor=admin_a, class_group=foreign)
        with pytest.raises(ValidationError):
            services.enrol_application(app, actor=admin_a, class_group=group, effective_from=group.academic_year.end_date + timedelta(days=1))
        assert not Student.objects.exists()


def test_grade_only_application_can_choose_class_at_confirmation(client, tenant_a, admin_a):
    group = make_class(tenant_a)
    app = application(tenant_a, admin_a, group=group, intended_class=None)
    with tenant_context(tenant_a):
        app = advance(advance(app, admin_a, "under_review"), admin_a, "accepted")
    client.force_login(admin_a)
    url = reverse("admissions:enrol", args=[app.pk])
    assert client.get(url).status_code == 200
    assert client.post(url, {"class_group": group.pk, "admission_number": "CUSTOM-001"}).status_code == 302
    assert client.post(url, {"class_group": group.pk}).status_code == 302
    with tenant_context(tenant_a):
        assert Student.objects.get().admission_number == "CUSTOM-001"


def test_permissions_platform_exclusion_and_service_denial(client, tenant_a, admin_a, teacher_a):
    app = application(tenant_a, admin_a, group=make_class(tenant_a))
    platform = get_user_model().objects.create_superuser("admissions-platform@example.test", "unused-password")
    Membership.objects.create(user=platform, tenant=tenant_a, role=Role.OWNER)
    urls = [reverse("admissions:dashboard"), reverse("admissions:list"), reverse("admissions:create"),
            detail(app), reverse("admissions:edit", args=[app.pk]), reverse("admissions:enrol", args=[app.pk])]
    assert client.get(urls[0]).url.startswith("/login/")
    for user in (teacher_a, platform):
        client.force_login(user)
        for url in urls:
            assert client.get(url).status_code == 403
            assert client.post(url, {}).status_code == 403
        with tenant_context(tenant_a):
            with pytest.raises(PermissionDenied):
                services.create_application(actor=user, data=applicant_data())
            with pytest.raises(PermissionDenied):
                advance(app, user, "under_review")
    with pytest.raises(PermissionDenied):
        services.create_application(actor=admin_a, data=applicant_data())


def test_cross_tenant_queries_documents_and_relationships(client, tenant_a, tenant_b, admin_a, admin_b):
    group_a, group_b = make_class(tenant_a), make_class(tenant_b)
    other = application(tenant_b, admin_b, group=group_b)
    with tenant_context(tenant_b):
        document = services.upload_document(other, actor=admin_b, kind="other", title="Private", file=pdf())
        guardian = Guardian.objects.create(first_name="Foreign", last_name="Guardian")
    client.force_login(admin_a)
    for url in (detail(other), reverse("admissions:edit", args=[other.pk]),
                reverse("admissions:document-download", args=[other.pk, document.pk])):
        assert client.get(url).status_code == 404
    with tenant_context(tenant_a):
        assert not StudentApplication.objects.exists()
        with pytest.raises(ValidationError):
            services.create_application(actor=admin_a, data=applicant_data(group_b))
        with pytest.raises(ValidationError):
            services.create_application(actor=admin_a, data=applicant_data(group_a, guardian=guardian))
        with pytest.raises(ValidationError):
            services.application_history(other, actor=admin_a)
    response = client.get(reverse("admissions:list"), {"academic_year": group_b.academic_year_id})
    assert response.context["filters"].errors and len(response.context["page"]) == 0


def test_application_documents_validate_and_are_private(client, tenant_a, admin_a, teacher_a):
    app = application(tenant_a, admin_a, group=make_class(tenant_a))
    client.force_login(admin_a)
    response = client.post(detail(app), {"action": "document", "document-kind": "transfer_letter",
        "document-title": "Transfer", "document-file": pdf()})
    assert response.status_code == 302
    with tenant_context(tenant_a):
        document = ApplicationDocument.objects.get()
        with pytest.raises(ValueError):
            _ = document.file.url
    url = reverse("admissions:document-download", args=[app.pk, document.pk])
    response = client.get(url)
    assert response.status_code == 200 and response["Content-Disposition"].startswith("attachment;")
    assert response["X-Content-Type-Options"] == "nosniff" and response["Cache-Control"] == "private, no-store"
    assert b"".join(response.streaming_content).startswith(b"%PDF-")
    assert client.get("/media/" + document.file.name).status_code == 404
    response = client.post(detail(app), {"action": "document", "document-kind": "other", "document-title": "Bad",
        "document-file": SimpleUploadedFile("malware.exe", b"MZ")})
    assert response.status_code == 400 and response.context["document_form"].errors
    client.force_login(teacher_a)
    assert client.get(url).status_code == 403


def test_dashboard_counts_and_directory_search(client, tenant_a, tenant_b, admin_a, admin_b):
    group_a, group_b = make_class(tenant_a), make_class(tenant_b)
    app = application(tenant_a, admin_a, group=group_a)
    application(tenant_b, admin_b, group=group_b, first_name="Foreign secret")
    client.force_login(admin_a)
    response = client.get(reverse("admissions:dashboard"))
    cards = {key: count for key, label, count in response.context["cards"]}
    assert cards["total"] == 1 and cards["submitted"] == 1 and cards["accepted"] == 0
    assert b"Foreign secret" not in response.content
    assert b"Admissions" in response.content
    for query in ({"q": "Tariro Dube"}, {"q": app.reference}, {"q": "Parent Dube"},
                  {"status": "submitted", "grade": group_a.grade_id, "academic_year": group_a.academic_year_id}):
        response = client.get(reverse("admissions:list"), query)
        assert [row.pk for row in response.context["page"]] == [app.pk]


def test_notes_and_decision_history_are_append_only(tenant_a, admin_a):
    app = application(tenant_a, admin_a, group=make_class(tenant_a))
    with tenant_context(tenant_a):
        event = services.add_review_note(app, actor=admin_a, body="Confidential review information")
        note = ApplicationNote.objects.get(audit_event=event)
        assert "Confidential" not in str(event.metadata) and not event.changes
        with pytest.raises(RuntimeError):
            note.save()
        with pytest.raises(RuntimeError):
            note.delete()
        with pytest.raises(RuntimeError):
            ApplicationNote.objects.filter(pk=note.pk).update(body="Rewritten")
        with pytest.raises(RuntimeError):
            ApplicationNote.objects.filter(pk=note.pk).delete()


def test_csrf_protection_and_status_tampering(client, tenant_a, admin_a):
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(admin_a)
    assert csrf.post(reverse("admissions:create"), {}).status_code == 403
    client.force_login(admin_a)
    data = {"first_name": "Tampered", "last_name": "Status", "application_date": timezone.localdate(),
            "status": "enrolled", "tenant": "other"}
    assert client.post(reverse("admissions:create"), data).status_code == 302
    with tenant_context(tenant_a):
        app = StudentApplication.objects.get()
        assert app.status == "draft" and app.tenant == tenant_a and app.student_id is None


def test_students_entitlement_is_enforced_in_services_and_views(client, tenant_a, admin_a):
    Entitlement.objects.filter(tenant=tenant_a, module_id="students").update(status="revoked")
    client.force_login(admin_a)
    assert client.get(reverse("admissions:dashboard")).status_code == 403
    with tenant_context(tenant_a), pytest.raises(PermissionDenied):
        services.create_application(actor=admin_a, data=applicant_data())


def test_database_constraints_prevent_fake_enrolment(tenant_a, admin_a):
    app = application(tenant_a, admin_a, submit=False)
    with tenant_context(tenant_a), pytest.raises(IntegrityError), transaction.atomic():
        StudentApplication.objects.filter(pk=app.pk).update(status="enrolled")


def test_review_interface_records_decisions_and_rejects_stale_posts(client, tenant_a, admin_a):
    app = application(tenant_a, admin_a, group=make_class(tenant_a))
    client.force_login(admin_a)
    form = client.get(detail(app)).context["transition_form"]
    posted = {"action": "transition", "target": "under_review",
              "expected_updated_at": form["expected_updated_at"].value()}
    assert client.post(detail(app), posted).status_code == 302
    assert client.post(detail(app), posted).status_code == 400
    form = client.get(detail(app)).context["transition_form"]
    posted.update(target="accepted", expected_updated_at=form["expected_updated_at"].value())
    assert client.post(detail(app), posted).status_code == 400  # A decision needs a reason.
    posted["reason"] = "Reviewed and approved"
    assert client.post(detail(app), posted).status_code == 302
    html = client.get(detail(app)).content
    assert b"Reviewed and approved" in html and b"Enrol applicant" in html
    assert admin_a.get_short_name().encode() in html


def test_pagination_preserves_filters(client, tenant_a, admin_a):
    with tenant_context(tenant_a):
        for index in range(26):
            services.create_application(actor=admin_a, data=applicant_data(first_name=f"Applicant {index}"))
    client.force_login(admin_a)
    response = client.get(reverse("admissions:list"), {"status": "draft", "page": 2})
    assert len(response.context["page"]) == 1 and b"status=draft" in response.content


@pytest.mark.parametrize("role", [Role.TEACHER, Role.HOD, Role.BURSAR, Role.STAFF, Role.GUARDIAN, Role.STUDENT])
def test_school_roles_without_admissions_permission_are_denied(client, tenant_a, role):
    user = make_user(tenant_a, role, email=f"admissions-{role}@example.test")
    client.force_login(user)
    assert client.get(reverse("admissions:dashboard")).status_code == 403
    with tenant_context(tenant_a), pytest.raises(PermissionDenied):
        services.create_application(actor=user, data=applicant_data())


def test_owner_can_use_school_admissions(client, tenant_a):
    owner = make_user(tenant_a, Role.OWNER)
    client.force_login(owner)
    assert client.get(reverse("admissions:dashboard")).status_code == 200
    with tenant_context(tenant_a):
        assert services.create_application(actor=owner, data=applicant_data()).status == "draft"


def test_same_tenant_placement_mismatch_and_future_birth_date_are_rejected(tenant_a, admin_a):
    from apps.academics.models import AcademicYear, Grade

    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        other_year = AcademicYear.objects.create(name="Next year", status=AcademicYear.Status.PLANNED, start_date=group.academic_year.end_date + timedelta(days=1),
                                                  end_date=group.academic_year.end_date + timedelta(days=366))
        other_grade = Grade.objects.create(name="Other grade")
        for data in (applicant_data(group, intended_year=other_year), applicant_data(group, intended_grade=other_grade),
                     applicant_data(group, date_of_birth=timezone.localdate() + timedelta(days=1))):
            with pytest.raises(ValidationError):
                services.create_application(actor=admin_a, data=data)


def test_admission_number_conflict_leaves_no_partial_enrolment(tenant_a, admin_a):
    group = make_class(tenant_a)
    app = accepted(tenant_a, admin_a, group)
    with tenant_context(tenant_a):
        services.student_services.create_student(first_name="Existing", last_name="Learner", admission_number="TAKEN")
        with pytest.raises(ValidationError):
            services.enrol_application(app, actor=admin_a, class_group=group, admission_number="TAKEN")
        assert Student.objects.count() == 1 and not Guardian.objects.exists()
        app.refresh_from_db()
        assert app.status == "accepted" and app.student_id is None
