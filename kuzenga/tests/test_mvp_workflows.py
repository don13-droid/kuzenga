from datetime import date

from django.urls import reverse

from apps.attendance.models import AttendanceRecord, AttendanceSession
from apps.core.context import tenant_context
from apps.students import services
from apps.students.models import StudentEnrolment
from apps.tenancy.models import TenantConfiguration

from .conftest import make_class


def test_enrolment_move_preserves_history(tenant_a):
    class_a = make_class(tenant_a, "4A")
    with tenant_context(tenant_a):
        from apps.academics.models import ClassGroup

        class_b = ClassGroup.objects.create(
            academic_year=class_a.academic_year, grade=class_a.grade, name="4B"
        )
        student = services.create_student(first_name="Tendai", last_name="Ncube")
        services.enrol_student(student, class_a, effective_from=date(2026, 1, 5))
        services.enrol_student(student, class_b, effective_from=date(2026, 6, 1))
        history = list(StudentEnrolment.objects.filter(student=student).order_by("effective_from"))
    assert len(history) == 2
    assert history[0].effective_to == date(2026, 5, 31)
    assert history[1].effective_to is None


def test_duplicate_student_is_rejected_by_form(client, tenant_a, admin_a):
    client.force_login(admin_a)
    data = {"first_name": "Ruva", "last_name": "Dube", "date_of_birth": "2012-03-04"}
    assert client.post(reverse("students:create"), data).status_code == 302
    resp = client.post(reverse("students:create"), data)
    assert resp.status_code == 200 and b"already exists" in resp.content


def test_duplicate_class_name_gives_form_error_not_500(client, tenant_a, admin_a):
    cg = make_class(tenant_a, "4A")
    client.force_login(admin_a)
    data = {"academic_year": cg.academic_year_id, "grade": cg.grade_id, "name": "4A"}
    resp = client.post(reverse("academics:create", args=["classes"]), data)
    assert resp.status_code == 200  # re-rendered with a validation error


def test_form_dropdowns_only_offer_own_tenant_data(client, tenant_a, tenant_b, admin_a):
    other = make_class(tenant_b, "9Z")
    client.force_login(admin_a)
    html = client.get(reverse("students:create")).content.decode()
    assert str(other.pk) not in html


def test_attendance_register_end_to_end(client, tenant_a, admin_a):
    class_a = make_class(tenant_a)
    with tenant_context(tenant_a):
        s1 = services.create_student(first_name="Anesu", last_name="A", class_group=class_a)
        s2 = services.create_student(first_name="Blessing", last_name="B", class_group=class_a)
    client.force_login(admin_a)
    url = reverse("attendance:register", args=[class_a.pk])
    assert client.get(url).status_code == 200
    resp = client.post(
        url, {f"status_{s1.pk}": "present", f"status_{s2.pk}": "absent", f"note_{s2.pk}": "sick"}
    )
    assert resp.status_code == 302
    with tenant_context(tenant_a):
        session = AttendanceSession.objects.get()
        assert session.status == "submitted"
        assert AttendanceRecord.objects.get(student=s2).status == "absent"
    # second submit is ignored/blocked: register is now read-only
    client.post(url, {f"status_{s2.pk}": "present"})
    with tenant_context(tenant_a):
        assert AttendanceRecord.objects.get(student=s2).status == "absent"


def test_attendance_cannot_open_other_tenants_class(client, tenant_a, tenant_b, admin_a):
    other_class = make_class(tenant_b)
    client.force_login(admin_a)
    assert client.get(reverse("attendance:register", args=[other_class.pk])).status_code == 404


def test_attendance_register_uses_and_enforces_tenant_configured_statuses(
    client, tenant_a, admin_a, tenant_b, admin_b
):
    class_a = make_class(tenant_a)
    class_b = make_class(tenant_b)
    with tenant_context(tenant_a):
        student = services.create_student(first_name="Anesu", last_name="A", class_group=class_a)
    configuration, _created = TenantConfiguration.objects.get_or_create(tenant=tenant_a)
    configuration.attendance_statuses = [
        {"code": "present", "label": "Present"},
        {"code": "absent", "label": "Absent"},
        {"code": "remote", "label": "Remote learning"},
    ]
    configuration.save(update_fields=("attendance_statuses", "updated_at"))

    client.force_login(admin_a)
    url = reverse("attendance:register", args=[class_a.pk])
    response = client.get(url)
    assert b'value="remote"' in response.content
    assert b"Remote learning" in response.content
    assert b"Late arrival threshold: 15 minutes" in response.content

    client.force_login(admin_b)
    other_tenant_response = client.get(reverse("attendance:register", args=[class_b.pk]))
    assert other_tenant_response.status_code == 200
    assert b'value="remote"' not in other_tenant_response.content

    client.force_login(admin_a)
    response = client.post(url, {f"status_{student.pk}": "remote"})
    assert response.status_code == 302
    with tenant_context(tenant_a):
        assert AttendanceRecord.objects.get(student=student).status == "remote"
    response = client.get(url)
    assert b"Remote learning" in response.content

    session = AttendanceSession.unscoped.get(class_group=class_a)
    session.status = AttendanceSession.Status.OPEN
    session.save(update_fields=("status", "updated_at"))
    response = client.post(url, {f"status_{student.pk}": "unapproved"})
    assert response.status_code == 200
    with tenant_context(tenant_a):
        assert AttendanceRecord.objects.get(student=student).status == "remote"
