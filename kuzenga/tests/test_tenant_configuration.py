from datetime import date
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.academics.models import (
    AcademicYear,
    AssessmentCategory,
    ClassGroup,
    Department,
    Grade,
    GradeBoundary,
    SchoolCalendarEvent,
    Subject,
    Term,
)
from apps.core.context import tenant_context
from apps.core.models import AuditEvent
from apps.tenancy.models import TenantConfiguration

User = get_user_model()


def superuser():
    return User.objects.create_superuser("configuration-platform@example.test", "unused-password")


def section_url(tenant, section):
    return reverse("superuser:tenant-configuration-section", args=[tenant.pk, section])


@pytest.mark.django_db
def test_configuration_get_creates_safe_defaults_and_is_tenant_specific(client, tenant_a, tenant_b):
    client.force_login(superuser())
    response = client.get(reverse("superuser:tenant-configuration", args=[tenant_a.pk]))

    assert response.status_code == 200
    assert tenant_a.name.encode() in response.content
    assert tenant_b.name.encode() not in response.content
    config = TenantConfiguration.objects.get(tenant=tenant_a)
    assert config.attendance_statuses == [
        {"code": "present", "label": "Present"},
        {"code": "absent", "label": "Absent"},
        {"code": "late", "label": "Late"},
        {"code": "excused", "label": "Excused"},
    ]
    assert config.late_arrival_threshold_minutes == 15
    assert reverse("superuser:tenant-configuration", args=[tenant_a.pk]).encode() in response.content


@pytest.mark.django_db
def test_configuration_requires_platform_superuser_and_rejects_school_users(
    client, tenant_a, tenant_b, admin_a, admin_b
):
    url = reverse("superuser:tenant-configuration", args=[tenant_b.pk])
    assert client.get(url).status_code == 302
    client.force_login(admin_a)
    assert client.get(url).status_code == 403
    assert client.post(section_url(tenant_b, "notifications"), {"notify_by_email": "on"}).status_code == 403
    client.force_login(admin_b)
    assert client.get(section_url(tenant_b, "classes")).status_code == 403


@pytest.mark.django_db
def test_academic_year_and_term_can_be_created_and_updated_with_tenant_scoping(client, tenant_a, tenant_b):
    with tenant_context(tenant_b):
        other_year = AcademicYear.objects.create(
            name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), is_current=True
        )
    client.force_login(superuser())

    year_data = {
        "name": "2027",
        "start_date": "2027-01-01",
        "end_date": "2027-12-31",
        "status": AcademicYear.Status.ACTIVE,
        "is_current": "on",
    }
    created = client.post(section_url(tenant_a, "academic-years"), year_data)
    year = AcademicYear.unscoped.get(tenant=tenant_a)
    assert created.status_code == 302
    assert year.is_current
    assert AcademicYear.unscoped.get(pk=other_year.pk).is_current

    year_data.update(name="School year 2027", end_date="2027-11-30")
    updated = client.post(
        reverse("superuser:tenant-configuration-edit", args=[tenant_a.pk, "academic-years", year.pk]),
        year_data,
    )
    year.refresh_from_db()
    assert updated.status_code == 302
    assert year.name == "School year 2027"
    assert year.end_date == date(2027, 11, 30)

    second_year = {
        "name": "2028",
        "start_date": "2028-01-01",
        "end_date": "2028-12-31",
        "status": AcademicYear.Status.PLANNED,
        "is_current": "on",
    }
    client.post(section_url(tenant_a, "academic-years"), second_year)
    year.refresh_from_db()
    assert not year.is_current
    assert AcademicYear.unscoped.get(tenant=tenant_a, name="2028").is_current

    term_data = {
        "academic_year": str(year.pk),
        "name": "Term 1",
        "start_date": "2027-01-10",
        "end_date": "2027-04-10",
    }
    term_response = client.post(section_url(tenant_a, "terms"), term_data)
    term = Term.unscoped.get(tenant=tenant_a)
    assert term_response.status_code == 302
    assert term.academic_year_id == year.pk

    invalid_term = client.post(
        section_url(tenant_a, "terms"),
        {**term_data, "name": "Outside year", "start_date": "2028-01-01", "end_date": "2028-02-01"},
    )
    assert invalid_term.status_code == 400
    assert Term.unscoped.filter(tenant=tenant_a).count() == 1


@pytest.mark.django_db
def test_academic_calendar_supports_holidays_opening_and_closing_dates(client, tenant_a):
    with tenant_context(tenant_a):
        year = AcademicYear.objects.create(
            name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), is_current=True
        )
    client.force_login(superuser())
    event = {
        "academic_year": str(year.pk),
        "title": "Mid-year break",
        "kind": SchoolCalendarEvent.Kind.HOLIDAY,
        "start_date": "2026-06-01",
        "end_date": "2026-06-14",
        "notes": "School closed",
    }
    assert client.post(section_url(tenant_a, "calendar"), event).status_code == 302
    saved_event = SchoolCalendarEvent.unscoped.get(tenant=tenant_a)
    edit_url = reverse("superuser:tenant-configuration-edit", args=[tenant_a.pk, "calendar", saved_event.pk])
    response = client.post(edit_url, {**event, "kind": SchoolCalendarEvent.Kind.OPENING, "title": "First day"})
    saved_event.refresh_from_db()
    assert response.status_code == 302
    assert saved_event.kind == SchoolCalendarEvent.Kind.OPENING
    assert saved_event.title == "First day"


@pytest.mark.django_db
def test_school_identity_reuses_existing_tenant_name_and_logo(client, tenant_a):
    client.force_login(superuser())
    output = BytesIO()
    Image.new("RGB", (8, 8), (12, 34, 56)).save(output, format="PNG")
    upload = SimpleUploadedFile("school.png", output.getvalue(), content_type="image/png")
    response = client.post(
        section_url(tenant_a, "identity"),
        {"name": "Updated School Name", "logo": upload},
    )
    tenant_a.refresh_from_db()
    assert response.status_code == 302
    assert tenant_a.name == "Updated School Name"
    assert tenant_a.logo.name.startswith("tenant-logos/")
    assert tenant_a.logo.storage.exists(tenant_a.logo.name)


@pytest.mark.django_db
def test_school_identity_updates_existing_contact_details_without_a_parallel_profile(client, tenant_a):
    client.force_login(superuser())
    response = client.post(
        section_url(tenant_a, "identity"),
        {
            "name": tenant_a.name,
            "school_email": "office@example.test",
            "school_primary_phone": "+263 4 123456",
            "school_alternative_phone": "+263 77 1234567",
            "physical_address": "10 School Road",
            "postal_address": "P.O. Box 123",
            "website": "https://school.example.test",
        },
    )
    tenant_a.refresh_from_db()
    assert response.status_code == 302
    assert tenant_a.school_email == "office@example.test"
    assert tenant_a.school_primary_phone == "+263 4 123456"
    assert tenant_a.school_alternative_phone == "+263 77 1234567"
    assert tenant_a.physical_address == "10 School Road"
    assert tenant_a.postal_address == "P.O. Box 123"
    assert tenant_a.website == "https://school.example.test"
    event = AuditEvent.objects.filter(
        tenant=tenant_a, action="tenant.configuration_changed", metadata__section="identity"
    ).latest("created_at")
    assert event.actor.is_superuser
    assert event.category == AuditEvent.Category.CONFIGURATION
    assert event.changes["school_email"] == "[REDACTED]"
    assert event.request_method == "POST"


@pytest.mark.django_db
def test_academic_year_ranges_cannot_overlap(client, tenant_a):
    with tenant_context(tenant_a):
        AcademicYear.objects.create(
            name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), is_current=True
        )
    client.force_login(superuser())

    response = client.post(
        section_url(tenant_a, "academic-years"),
        {
            "name": "Academic 2026",
            "start_date": "2026-10-01",
            "end_date": "2027-09-30",
            "status": AcademicYear.Status.PLANNED,
        },
    )
    assert response.status_code == 400
    assert AcademicYear.unscoped.filter(tenant=tenant_a).count() == 1


@pytest.mark.django_db
def test_academic_relationship_forms_reject_records_from_another_tenant(client, tenant_a, tenant_b):
    with tenant_context(tenant_b):
        foreign_year = AcademicYear.objects.create(
            name="2027", start_date=date(2027, 1, 1), end_date=date(2027, 12, 31), is_current=True
        )
    client.force_login(superuser())
    response = client.post(
        section_url(tenant_a, "terms"),
        {
            "academic_year": str(foreign_year.pk),
            "name": "Foreign term",
            "start_date": "2027-02-01",
            "end_date": "2027-04-01",
        },
    )
    assert response.status_code == 400
    assert not Term.unscoped.filter(tenant=tenant_a).exists()


@pytest.mark.django_db
def test_school_structure_allows_flexible_levels_classes_streams_and_departments(client, tenant_a):
    with tenant_context(tenant_a):
        year = AcademicYear.objects.create(
            name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), is_current=True
        )
    client.force_login(superuser())

    response = client.post(
        section_url(tenant_a, "levels"),
        {"name": "Senior Form 4", "education_level": "Upper Secondary", "level_order": "10", "is_active": "on"},
    )
    grade = Grade.unscoped.get(tenant=tenant_a)
    assert response.status_code == 302
    assert grade.education_level == "Upper Secondary"

    class_data = {
        "academic_year": str(year.pk),
        "grade": str(grade.pk),
        "name": "Blue Stream",
        "capacity": "32",
        "is_active": "on",
    }
    response = client.post(section_url(tenant_a, "classes"), class_data)
    class_group = ClassGroup.unscoped.get(tenant=tenant_a)
    assert response.status_code == 302
    assert class_group.name == "Blue Stream"
    assert class_group.capacity == 32

    edit_url = reverse("superuser:tenant-configuration-edit", args=[tenant_a.pk, "classes", class_group.pk])
    response = client.post(edit_url, {**class_data, "capacity": "36", "name": "Gold Stream"})
    class_group.refresh_from_db()
    assert response.status_code == 302
    assert class_group.capacity == 36
    assert class_group.name == "Gold Stream"

    response = client.post(
        section_url(tenant_a, "departments"),
        {"name": "Sciences", "code": "sciences", "is_active": "on"},
    )
    assert response.status_code == 302
    department = Department.unscoped.get(tenant=tenant_a)
    deactivate = reverse("superuser:tenant-configuration-toggle", args=[tenant_a.pk, "departments", department.pk])
    response = client.post(deactivate, {"active": "false"})
    department.refresh_from_db()
    assert response.status_code == 302
    assert not department.is_active

    subject_response = client.post(
        section_url(tenant_a, "subjects"),
        {"code": "SCI", "name": "Integrated Science"},
    )
    assert subject_response.status_code == 302
    assert Subject.unscoped.get(tenant=tenant_a, code="SCI").name == "Integrated Science"


@pytest.mark.django_db
def test_assessment_marks_and_grade_boundaries_are_validated(client, tenant_a):
    client.force_login(superuser())
    assessment = {
        "name": "Mid-year examination",
        "kind": AssessmentCategory.Kind.EXAMINATION,
        "minimum_marks": "0",
        "maximum_marks": "100",
        "pass_marks": "50",
        "is_active": "on",
    }
    response = client.post(section_url(tenant_a, "assessment"), assessment)
    assert response.status_code == 302
    assert AssessmentCategory.unscoped.get(tenant=tenant_a).pass_marks == 50

    invalid = client.post(section_url(tenant_a, "assessment"), {**assessment, "name": "Invalid", "pass_marks": "101"})
    assert invalid.status_code == 400
    assert AssessmentCategory.unscoped.filter(tenant=tenant_a).count() == 1

    boundary = {"grade": "A", "minimum_percent": "80", "maximum_percent": "100", "is_pass": "on"}
    assert client.post(section_url(tenant_a, "grading"), boundary).status_code == 302
    overlap = client.post(
        section_url(tenant_a, "grading"),
        {"grade": "B", "minimum_percent": "70", "maximum_percent": "85", "is_pass": "on"},
    )
    assert overlap.status_code == 400
    assert GradeBoundary.unscoped.filter(tenant=tenant_a).count() == 1


@pytest.mark.django_db
def test_attendance_regional_and_notification_preferences_save(client, tenant_a):
    client.force_login(superuser())
    attendance = {
        "attendance_statuses": "present | Present\nabsent | Absent\nlate | Late\nexcused | Excused\nremote | Remote",
        "late_arrival_threshold_minutes": "20",
        "attendance_reporting": "weekly",
    }
    assert client.post(section_url(tenant_a, "attendance"), attendance).status_code == 302

    regional = {
        "country": "zw",
        "default_currency": "USD",
        "timezone": "Africa/Harare",
        "date_format": "Y-m-d",
        "language": "en-ZW",
        "measurement_system": "metric",
    }
    assert client.post(section_url(tenant_a, "regional"), regional).status_code == 302
    assert client.post(
        section_url(tenant_a, "notifications"),
        {"notify_by_email": "on", "notify_academic_calendar": "on"},
    ).status_code == 302

    config = TenantConfiguration.objects.get(tenant=tenant_a)
    tenant_a.refresh_from_db()
    assert config.late_arrival_threshold_minutes == 20
    assert config.attendance_reporting == TenantConfiguration.AttendanceReporting.WEEKLY
    assert config.attendance_statuses[-1] == {"code": "remote", "label": "Remote"}
    assert config.date_format == "Y-m-d"
    assert config.language == "en-ZW"
    assert tenant_a.country == "ZW"
    assert not config.notify_in_system
    assert config.notify_by_email
    assert config.notify_academic_calendar


@pytest.mark.django_db
def test_configuration_lists_and_edit_urls_never_resolve_another_tenants_record(
    client, tenant_a, tenant_b
):
    with tenant_context(tenant_b):
        foreign_grade = Grade.objects.create(name="Private Form", level_order=1)
        foreign_subject = Subject.objects.create(code="PRIVATE", name="Private Subject")
    client.force_login(superuser())

    response = client.get(section_url(tenant_a, "levels"))
    assert response.status_code == 200
    assert b"Private Form" not in response.content
    subjects_response = client.get(section_url(tenant_a, "subjects"))
    assert subjects_response.status_code == 200
    assert b"Private Subject" not in subjects_response.content
    foreign_url = reverse("superuser:tenant-configuration-edit", args=[tenant_a.pk, "levels", foreign_grade.pk])
    assert client.get(foreign_url).status_code == 404
    assert client.post(foreign_url, {"name": "Stolen", "level_order": "1"}).status_code == 404
    foreign_subject_url = reverse(
        "superuser:tenant-configuration-edit", args=[tenant_a.pk, "subjects", foreign_subject.pk]
    )
    assert client.get(foreign_subject_url).status_code == 404
