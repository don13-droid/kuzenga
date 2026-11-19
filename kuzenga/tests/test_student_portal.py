from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.urls import reverse

from apps.core.context import tenant_context
from apps.core.models import AuditEvent
from apps.students import services
from apps.students.forms import StudentForm
from apps.students.models import Student
from apps.tenancy.middleware import SESSION_KEY
from apps.tenancy.models import Entitlement, Membership, Role

from .conftest import make_class, make_user

pytestmark = pytest.mark.django_db


def test_portal_user_database_constraint_matches_model_and_foreign_key():
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, Student._meta.db_table)
        unique = constraints["uniq_student_portal_user"]
        assert unique["unique"]
        assert unique["columns"] == ["tenant_id", "portal_user_id"]
        user_model = get_user_model()
        assert any(
            details["columns"] == ["portal_user_id"]
            and details["foreign_key"] == (user_model._meta.db_table, user_model._meta.pk.column)
            for details in constraints.values()
        )
        if connection.vendor == "postgresql":
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                "WHERE conrelid = %s::regclass AND conname = %s AND contype = 'u')",
                [Student._meta.db_table, "uniq_student_portal_user"],
            )
            assert cursor.fetchone()[0], "PostgreSQL needs a constraint, not only a unique index"


@pytest.fixture
def portal_student(tenant_a, admin_a):
    user = make_user(tenant_a, Role.STUDENT)
    group = make_class(tenant_a)
    with tenant_context(tenant_a):
        student = services.create_student(
            first_name="Personal", last_name="Learner", date_of_birth=date(2012, 3, 4),
            portal_user=user, class_group=group, actor=admin_a,
        )
    return user, student, group


def test_student_password_login_displays_only_personal_profile_and_placements(
    client, tenant_a, admin_a, portal_student
):
    user, student, group = portal_student
    with tenant_context(tenant_a):
        other = services.create_student(first_name="Hidden", last_name="Classmate")
    response = client.post(reverse("login"), {"username": user.email, "password": "pass12345!"})
    assert response.url == reverse("dashboard")
    dashboard = client.get(response.url, {"student": str(other.pk)})
    assert dashboard.status_code == 200
    assert dashboard.context["student_profile"] == student
    assert [row.class_group_id for row in dashboard.context["student_enrolments"]] == [group.pk]
    assert b"Personal Learner" in dashboard.content
    assert student.admission_number.encode() in dashboard.content
    assert b"Hidden Classmate" not in dashboard.content
    assert b"Active learners" not in dashboard.content
    assert "stats" not in dashboard.context
    assert client.post(reverse("logout")).status_code == 302
    assert "_auth_user_id" not in client.session


def test_student_cannot_open_or_mutate_staff_student_records(client, portal_student):
    user, student, _group = portal_student
    client.force_login(user)
    for name in ("students:detail", "students:edit"):
        assert client.get(reverse(name, args=[student.pk])).status_code == 403
    assert client.post(reverse("students:detail", args=[student.pk]), {
        "action": "status", "status": "withdrawn", "reason": "Denied request",
    }).status_code == 403
    assert client.post(reverse("dashboard"), {"portal_user": str(user.pk)}).status_code == 405


def test_student_profile_is_never_inferred_from_name_or_email(client, tenant_a, admin_a):
    user = make_user(tenant_a, Role.STUDENT)
    with tenant_context(tenant_a):
        services.create_student(first_name=user.email, last_name="Unlinked", actor=admin_a)
    client.force_login(user)
    response = client.get(reverse("dashboard"))
    assert response.context["student_profile"] is None
    assert b"Your student profile is not linked yet" in response.content


def test_same_identity_can_have_separate_explicit_records_in_two_schools(
    client, tenant_a, tenant_b, admin_b, portal_student
):
    user, own_a, _group = portal_student
    Membership.objects.create(user=user, tenant=tenant_b, role=Role.STUDENT)
    with tenant_context(tenant_b):
        own_b = services.create_student(
            first_name="Other school", last_name="Personal record", portal_user=user, actor=admin_b,
        )
    client.force_login(user)
    for tenant, own, hidden in ((tenant_a, own_a, own_b), (tenant_b, own_b, own_a)):
        session = client.session
        session[SESSION_KEY] = str(tenant.pk)
        session.save()
        response = client.get(reverse("dashboard"))
        assert response.context["student_profile"] == own
        assert hidden.full_name.encode() not in response.content


def test_revoked_student_membership_cannot_reuse_profile_binding(client, portal_student):
    user, _student, _group = portal_student
    client.force_login(user)
    Membership.objects.filter(user=user).update(status=Membership.Status.SUSPENDED)
    assert client.get(reverse("dashboard")).url == reverse("tenancy:select")


def test_role_change_stops_student_dashboard_access(client, portal_student):
    user, _student, _group = portal_student
    client.force_login(user)
    Membership.objects.filter(user=user).update(role=Role.STAFF)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert "student_profile" not in response.context
    assert b"My student dashboard" not in response.content


def test_inactive_identity_cannot_reuse_student_session(client, portal_student):
    user, _student, _group = portal_student
    client.force_login(user)
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert client.get(reverse("dashboard")).url == reverse("login")


def test_student_portal_respects_students_entitlement(client, tenant_a, portal_student):
    user, _student, _group = portal_student
    client.force_login(user)
    Entitlement.objects.filter(tenant=tenant_a, module_id="students").update(status=Entitlement.Status.REVOKED)
    assert client.get(reverse("dashboard")).status_code == 403


def test_administrator_can_explicitly_link_and_unlink_existing_student(
    client, tenant_a, admin_a
):
    user = make_user(tenant_a, Role.STUDENT)
    with tenant_context(tenant_a):
        student = services.create_student(first_name="Link", last_name="Me", actor=admin_a)
    client.force_login(admin_a)
    route = reverse("students:edit", args=[student.pk])
    response = client.post(route, {"first_name": "Link", "last_name": "Me", "portal_user": str(user.pk)})
    assert response.status_code == 302
    student.refresh_from_db()
    assert student.portal_user == user
    assert Membership.objects.get(user=user, tenant=tenant_a).role == Role.STUDENT
    assert AuditEvent.objects.filter(action="student.portal_link_changed", object_id=str(student.pk)).count() == 1
    response = client.post(route, {"first_name": "Link", "last_name": "Me", "portal_user": ""})
    assert response.status_code == 302
    student.refresh_from_db()
    assert student.portal_user_id is None
    assert AuditEvent.objects.filter(action="student.portal_link_changed", object_id=str(student.pk)).count() == 2


def test_administrator_can_link_new_student_and_owner_has_same_authority(client, tenant_a):
    owner = make_user(tenant_a, Role.OWNER)
    user = make_user(tenant_a, Role.STUDENT)
    client.force_login(owner)
    response = client.post(reverse("students:create"), {
        "first_name": "Created", "last_name": "With account", "portal_user": str(user.pk),
    })
    assert response.status_code == 302
    with tenant_context(tenant_a):
        student = Student.objects.get(portal_user=user)
    assert student.first_name == "Created"


def test_login_account_choices_only_include_available_active_students(
    client, tenant_a, tenant_b, admin_a, teacher_a, portal_student
):
    linked, _student, _group = portal_student
    eligible = make_user(tenant_a, Role.STUDENT, email="available@example.test")
    foreign = make_user(tenant_b, Role.STUDENT)
    inactive = make_user(tenant_a, Role.STUDENT, email="inactive@example.test")
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    invited = make_user(tenant_a, Role.STUDENT, email="invited@example.test")
    Membership.objects.filter(user=invited).update(status=Membership.Status.INVITED)
    client.force_login(admin_a)
    form = client.get(reverse("students:create")).context["form"]
    choices = set(form.fields["portal_user"].queryset.values_list("pk", flat=True))
    assert choices == {eligible.pk}
    assert not choices & {linked.pk, foreign.pk, inactive.pk, invited.pk, teacher_a.pk, admin_a.pk}


@pytest.mark.parametrize("kind", ["foreign", "teacher", "inactive", "platform", "staff", "invited", "suspended"])
def test_service_rejects_invalid_login_account_without_creating_student(
    tenant_a, tenant_b, admin_a, teacher_a, kind
):
    if kind == "foreign":
        user = make_user(tenant_b, Role.STUDENT)
    elif kind == "teacher":
        user = teacher_a
    elif kind == "inactive":
        user = make_user(tenant_a, Role.STUDENT)
        user.is_active = False
        user.save(update_fields=["is_active"])
    elif kind == "platform":
        user = get_user_model().objects.create_superuser("platform-student@example.test", "Not-used-813!")
        Membership.objects.create(user=user, tenant=tenant_a, role=Role.STUDENT)
    else:
        user = make_user(tenant_a, Role.STUDENT)
        if kind == "staff":
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        else:
            Membership.objects.filter(user=user).update(status=kind)
    with tenant_context(tenant_a):
        before = Student.objects.count()
        with pytest.raises(ValidationError):
            services.create_student(first_name="Denied", last_name="Binding", portal_user=user, actor=admin_a)
        assert Student.objects.count() == before


def test_binding_service_requires_explicit_school_administration(tenant_a):
    user = make_user(tenant_a, Role.STUDENT)
    with tenant_context(tenant_a), pytest.raises(PermissionDenied):
        services.create_student(first_name="Denied", last_name="Internal binding", portal_user=user)


def test_unauthorized_binding_field_is_rejected_in_form(tenant_a, teacher_a):
    user = make_user(tenant_a, Role.STUDENT)
    with tenant_context(tenant_a):
        form = StudentForm({"first_name": "No", "last_name": "Binding", "portal_user": str(user.pk)}, actor=teacher_a)
        assert "portal_user" not in form.fields
        assert not form.is_valid()
        assert "Only a school owner or administrator" in str(form.errors)


def test_duplicate_binding_is_rejected_by_service_and_database(tenant_a, admin_a, portal_student):
    user, _first, _group = portal_student
    with tenant_context(tenant_a):
        with pytest.raises(ValidationError):
            services.create_student(first_name="Duplicate", last_name="Binding", portal_user=user, actor=admin_a)
        second = services.create_student(first_name="Unlinked", last_name="Second", actor=admin_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            Student.objects.filter(pk=second.pk).update(portal_user=user)


def test_role_change_does_not_block_unrelated_student_edits(tenant_a, admin_a, portal_student):
    user, student, _group = portal_student
    Membership.objects.filter(user=user).update(role=Role.TEACHER)
    with tenant_context(tenant_a):
        services.update_student(student, actor=admin_a, first_name="Allowed update")
        services.change_student_status(student, status=Student.Status.SUSPENDED,
                                       reason="School record update", actor=admin_a)
        services.update_student(student, actor=admin_a, portal_user=None)
    student.refresh_from_db()
    assert student.first_name == "Allowed update"
    assert student.status == Student.Status.SUSPENDED
    assert student.portal_user_id is None


def test_existing_edit_that_omits_account_field_preserves_binding(client, admin_a, portal_student):
    user, student, _group = portal_student
    client.force_login(admin_a)
    response = client.post(reverse("students:edit", args=[student.pk]), {
        "first_name": "Updated", "last_name": "Learner",
    })
    assert response.status_code == 302
    student.refresh_from_db()
    assert student.portal_user_id == user.pk
    assert student.first_name == "Updated"


def test_foreign_account_post_is_rejected_without_changing_existing_student(
    client, tenant_a, tenant_b, admin_a, portal_student
):
    user, student, _group = portal_student
    foreign = make_user(tenant_b, Role.STUDENT)
    client.force_login(admin_a)
    response = client.post(reverse("students:edit", args=[student.pk]), {
        "first_name": "Tampered", "last_name": "Learner", "portal_user": str(foreign.pk),
    })
    assert response.status_code == 200
    assert "portal_user" in response.context["form"].errors
    student.refresh_from_db()
    assert student.portal_user_id == user.pk
    assert student.first_name == "Personal"
