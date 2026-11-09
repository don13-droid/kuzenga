from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.core.models import AuditEvent
from apps.tenancy.models import Membership, Role
from apps.tenancy.permissions import has_permission
from apps.tenancy.user_admin_services import create_tenant_member

User = get_user_model()


def make_platform_user():
    return User.objects.create_superuser("platform-user-admin@example.test", "Unused-password-1!")


@pytest.mark.django_db
def test_platform_directory_is_selected_tenant_scoped(client, tenant_a, tenant_b, admin_a, admin_b):
    client.force_login(make_platform_user())
    response = client.get(reverse("superuser:tenant-users", args=[tenant_a.pk]))

    assert response.status_code == 200
    assert admin_a.email.encode() in response.content
    assert admin_b.email.encode() not in response.content


@pytest.mark.django_db
def test_roles_matrix_and_teacher_directory_use_existing_roles(client, tenant_a, admin_a, teacher_a):
    client.force_login(make_platform_user())
    roles = client.get(reverse("superuser:tenant-user-roles", args=[tenant_a.pk]))
    teachers = client.get(
        reverse("superuser:tenant-users", args=[tenant_a.pk]), {"group": "teachers"}
    )

    assert roles.status_code == 200
    assert b"Manage school users and roles" in roles.content
    assert teachers.status_code == 200
    assert teacher_a.email.encode() in teachers.content
    assert admin_a.email.encode() not in teachers.content


@pytest.mark.django_db
def test_school_admin_can_only_manage_own_tenant_and_has_permission(client, tenant_a, tenant_b, admin_a, admin_b):
    client.force_login(admin_a)
    response = client.get(reverse("tenancy:users"))
    assert response.status_code == 200
    assert admin_a.email.encode() in response.content
    assert admin_b.email.encode() not in response.content
    assert client.get(reverse("superuser:tenant-users", args=[tenant_b.pk])).status_code == 403
    assert has_permission(Membership.objects.get(user=admin_a, tenant=tenant_a), "users.manage")
    other_membership = Membership.objects.get(user=admin_b, tenant=tenant_b)
    assert client.get(reverse("tenancy:user-profile", args=[other_membership.pk])).status_code == 404


@pytest.mark.django_db
def test_school_members_cannot_open_management_interface(client, teacher_a):
    client.force_login(teacher_a)
    assert client.get(reverse("tenancy:users")).status_code == 403


@pytest.mark.django_db
def test_user_management_service_rejects_actor_without_tenant_manage_permission(
    tenant_a, teacher_a
):
    with pytest.raises(PermissionDenied):
        create_tenant_member(
            tenant=tenant_a,
            data={"email": "unauthorized@example.test", "full_name": "Unauthorized", "role": Role.STAFF},
            actor=teacher_a,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Role.ADMIN, Role.TEACHER, Role.STAFF])
def test_platform_user_can_create_pending_school_membership(client, tenant_a, role):
    client.force_login(make_platform_user())
    response = client.post(
        reverse("superuser:tenant-user-create", args=[tenant_a.pk]),
        {
            "email": f"new-{role}@example.test",
            "full_name": "New School User",
            "phone": "+263 77 000 0000",
            "role": role,
        },
    )

    user = User.objects.get(email=f"new-{role}@example.test")
    membership = Membership.objects.get(user=user, tenant=tenant_a)
    assert response.status_code == 200
    assert "No email was sent" in response.content.decode()
    assert membership.status == Membership.Status.INVITED
    assert membership.role == role
    assert not user.has_usable_password()
    assert not user.is_superuser and not user.is_staff


@pytest.mark.django_db
def test_existing_identity_can_be_added_without_overwriting_global_profile(
    client, tenant_a, tenant_b
):
    shared_user = User.objects.create_user(
        "shared-identity@example.test", "Original-Password-421!", full_name="Original Name", phone="123"
    )
    Membership.objects.create(user=shared_user, tenant=tenant_b, role=Role.TEACHER)
    client.force_login(make_platform_user())

    response = client.post(
        reverse("superuser:tenant-user-create", args=[tenant_a.pk]),
        {
            "email": shared_user.email,
            "full_name": "Attempted Replacement",
            "phone": "999",
            "role": Role.ADMIN,
        },
    )

    shared_user.refresh_from_db()
    new_membership = Membership.objects.get(user=shared_user, tenant=tenant_a)
    assert response.status_code == 200
    assert new_membership.status == Membership.Status.INVITED
    assert new_membership.role == Role.ADMIN
    assert shared_user.full_name == "Original Name"
    assert shared_user.phone == "123"
    assert shared_user.check_password("Original-Password-421!")


@pytest.mark.django_db
def test_owner_role_cannot_be_assigned_or_primary_owner_deactivated(client, tenant_a, admin_a):
    owner_membership = Membership.objects.get(user=admin_a, tenant=tenant_a)
    owner_membership.role = Role.OWNER
    owner_membership.save(update_fields=["role", "updated_at"])
    client.force_login(make_platform_user())

    create = client.post(
        reverse("superuser:tenant-user-create", args=[tenant_a.pk]),
        {"email": "new-owner@example.test", "full_name": "Wrong Owner", "role": Role.OWNER},
    )
    deactivate = client.post(
        reverse("superuser:tenant-user-status", args=[tenant_a.pk, owner_membership.pk]),
        {"action": "deactivate"},
    )

    assert create.status_code == 400
    assert not User.objects.filter(email="new-owner@example.test").exists()
    assert not AuditEvent.objects.filter(tenant=tenant_a, action="tenant.user_invited").exists()
    assert deactivate.status_code == 302
    owner_membership.refresh_from_db()
    assert owner_membership.status == Membership.Status.ACTIVE


@pytest.mark.django_db
def test_membership_deactivation_does_not_disable_global_identity(client, tenant_a, admin_a, teacher_a):
    membership = Membership.objects.get(user=teacher_a, tenant=tenant_a)
    client.force_login(make_platform_user())

    response = client.post(
        reverse("superuser:tenant-user-status", args=[tenant_a.pk, membership.pk]),
        {"action": "deactivate"},
    )

    membership.refresh_from_db()
    teacher_a.refresh_from_db()
    assert response.status_code == 302
    assert membership.status == Membership.Status.SUSPENDED
    assert teacher_a.is_active


@pytest.mark.django_db
def test_edit_updates_tenant_role_and_user_details(client, tenant_a, teacher_a):
    membership = Membership.objects.get(user=teacher_a, tenant=tenant_a)
    client.force_login(make_platform_user())

    response = client.post(
        reverse("superuser:tenant-user-edit", args=[tenant_a.pk, membership.pk]),
        {
            "email": teacher_a.email,
            "full_name": "Updated Teacher",
            "phone": "+263770001111",
            "role": Role.HOD,
        },
    )

    teacher_a.refresh_from_db()
    membership.refresh_from_db()
    assert response.status_code == 302
    assert teacher_a.full_name == "Updated Teacher"
    assert teacher_a.phone == "+263770001111"
    assert membership.role == Role.HOD
    event = AuditEvent.objects.filter(
        tenant=tenant_a, action="tenant.user_updated", object_id=str(membership.pk)
    ).latest("created_at")
    assert event.actor.is_superuser
    assert event.target_user == teacher_a
    assert event.changes["role"] == {"before": Role.TEACHER, "after": Role.HOD}
    assert "full_name" in event.changes["profile_fields_updated"]


@pytest.mark.django_db
def test_profile_image_can_be_uploaded_and_replaced(client, tenant_a, teacher_a, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    membership = Membership.objects.get(user=teacher_a, tenant=tenant_a)
    client.force_login(make_platform_user())
    url = reverse("superuser:tenant-user-edit", args=[tenant_a.pk, membership.pk])
    image_buffer = BytesIO()
    Image.new("RGB", (2, 2), color="navy").save(image_buffer, format="PNG")
    png = image_buffer.getvalue()

    first = client.post(
        url,
        {
            "email": teacher_a.email,
            "full_name": "Image Teacher",
            "phone": "",
            "role": Role.TEACHER,
            "profile_image": SimpleUploadedFile("avatar.png", png, content_type="image/png"),
        },
    )
    teacher_a.refresh_from_db()
    first_name = teacher_a.profile_image.name
    second = client.post(
        url,
        {
            "email": teacher_a.email,
            "full_name": "Image Teacher",
            "phone": "",
            "role": Role.TEACHER,
            "profile_image": SimpleUploadedFile("avatar-new.png", png, content_type="image/png"),
        },
    )
    teacher_a.refresh_from_db()

    assert first.status_code == 302
    assert second.status_code == 302
    assert teacher_a.profile_image.name != first_name


@pytest.mark.django_db
def test_cannot_edit_membership_by_using_another_tenant_id(client, tenant_a, tenant_b, admin_b):
    membership = Membership.objects.get(user=admin_b, tenant=tenant_b)
    client.force_login(make_platform_user())

    response = client.get(reverse("superuser:tenant-user-profile", args=[tenant_a.pk, membership.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_activation_link_sets_password_and_activates_only_selected_membership(client, tenant_a):
    client.force_login(make_platform_user())
    created = client.post(
        reverse("superuser:tenant-user-create", args=[tenant_a.pk]),
        {"email": "activate-me@example.test", "full_name": "Activate Me", "role": Role.TEACHER},
    )
    membership = Membership.objects.get(user__email="activate-me@example.test", tenant=tenant_a)
    link = created.context["activation_url"]
    page = client.get(link)
    assert page.status_code == 200
    response = client.post(
        link,
        {"password1": "Safe-Long-Password-982!", "password2": "Safe-Long-Password-982!"},
    )

    membership.refresh_from_db()
    membership.user.refresh_from_db()
    assert response.status_code == 200
    assert membership.status == Membership.Status.ACTIVE
    assert membership.user.check_password("Safe-Long-Password-982!")


@pytest.mark.django_db
def test_password_reset_uses_one_time_django_token(client, tenant_a, teacher_a):
    membership = Membership.objects.get(user=teacher_a, tenant=tenant_a)
    client.force_login(make_platform_user())
    issued = client.post(
        reverse("superuser:tenant-user-password-reset", args=[tenant_a.pk, membership.pk])
    )
    link = issued.context["secure_url"]
    assert "Replacement-Password-421!" not in link
    assert client.get(link).status_code == 200

    response = client.post(
        link,
        {"password1": "Replacement-Password-421!", "password2": "Replacement-Password-421!"},
    )

    teacher_a.refresh_from_db()
    assert response.status_code == 200
    assert teacher_a.check_password("Replacement-Password-421!")
    assert client.get(link).status_code == 404


@pytest.mark.django_db
def test_separate_portals_accept_only_their_account_type(client, admin_a):
    platform = make_platform_user()
    school_response = client.post(
        reverse("login"), {"username": platform.email, "password": "Unused-password-1!"}
    )
    platform_response = client.post(
        reverse("platform-login"), {"username": admin_a.email, "password": "pass12345!"}
    )

    assert school_response.status_code == 200
    assert platform_response.status_code == 200
    assert client.get(reverse("platform-login")).status_code == 200
