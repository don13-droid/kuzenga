from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.core import audit

from .models import Membership, Role, Tenant
from .permissions import has_permission

MANAGEMENT_ROLES = (Role.OWNER, Role.ADMIN)
SCHOOL_USER_FILTER = {"user__is_superuser": False, "user__is_staff": False}


def _ensure_actor_can_manage_tenant(*, actor, tenant):
    if actor.is_superuser:
        return
    membership = Membership.objects.filter(
        tenant=tenant,
        user=actor,
        status=Membership.Status.ACTIVE,
    ).first()
    if not has_permission(membership, "users.manage"):
        raise PermissionDenied("You are not allowed to manage users for this school.")


def tenant_memberships(tenant):
    return Membership.objects.filter(tenant=tenant, **SCHOOL_USER_FILTER).select_related("user")


def get_tenant_membership(tenant, membership_id):
    return tenant_memberships(tenant).filter(pk=membership_id).first()


def _create_tenant_member(*, tenant, data, actor, request=None):
    _ensure_actor_can_manage_tenant(actor=actor, tenant=tenant)
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    User = get_user_model()
    email = data["email"].strip().lower()
    user = User.objects.select_for_update().filter(email__iexact=email).first()

    if user:
        if user.is_superuser or user.is_staff:
            raise ValidationError("Platform accounts cannot be added as school users.")
        if not user.is_active:
            raise ValidationError("This account is disabled by the platform administrator.")
        if Membership.objects.filter(tenant=tenant, user=user).exists():
            raise ValidationError("This account already belongs to the selected school.")
        created_user = False
    else:
        user = User(email=email, full_name=data["full_name"], phone=data.get("phone", ""))
        user.set_unusable_password()
        user.save()
        created_user = True

    role = data["role"]
    if role not in Role.values or role == Role.OWNER:
        raise ValidationError("Choose an existing school role. The primary owner role is protected.")

    membership = Membership.objects.create(
        tenant=tenant,
        user=user,
        role=role,
        status=Membership.Status.INVITED,
    )

    uploaded_image = data.get("profile_image")
    if created_user and uploaded_image:
        user.profile_image = uploaded_image
        user.save(update_fields=("profile_image", "updated_at"))

    audit.record(
        "tenant.user_invited",
        actor=actor,
        obj=membership,
        tenant=tenant,
        request=request,
        changes={
            "membership": {
                "before": None,
                "after": {"role": role, "status": Membership.Status.INVITED},
            }
        },
        role=role,
        new_account=created_user,
    )
    return membership, created_user


def create_tenant_member(*, tenant, data, actor, request=None):
    try:
        with transaction.atomic():
            return _create_tenant_member(tenant=tenant, data=data, actor=actor, request=request)
    except IntegrityError as exc:
        raise ValidationError("An account or school membership with these details already exists.") from exc


def update_tenant_member(*, tenant, membership_id, data, actor, request=None):
    with transaction.atomic():
        _ensure_actor_can_manage_tenant(actor=actor, tenant=tenant)
        tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
        membership = (
            Membership.objects.select_for_update()
            .select_related("user")
            .get(pk=membership_id, tenant=tenant, **SCHOOL_USER_FILTER)
        )
        user = get_user_model().objects.select_for_update().get(pk=membership.user_id)
        previous_role = membership.role
        role = data["role"]

        if membership.role == Role.OWNER and role != Role.OWNER:
            raise ValidationError("The primary school owner cannot be reassigned here.")
        if role not in Role.values or (role == Role.OWNER and membership.role != Role.OWNER):
            raise ValidationError("Choose an existing school role. The primary owner role is protected.")

        if (
            membership.status == Membership.Status.ACTIVE
            and membership.role in MANAGEMENT_ROLES
            and role not in MANAGEMENT_ROLES
            and not Membership.objects.filter(
                tenant=tenant,
                status=Membership.Status.ACTIVE,
                role__in=MANAGEMENT_ROLES,
            )
            .exclude(pk=membership.pk)
            .exists()
        ):
            raise ValidationError("Keep at least one active school administrator.")

        shared_identity = Membership.objects.filter(user=user).exclude(tenant=tenant).exists()
        profile_values = {
            "email": data["email"],
            "full_name": data["full_name"],
            "phone": data.get("phone", ""),
        }
        changed_profile_fields = sorted(
            key for key, value in profile_values.items() if getattr(user, key) != value
        )
        changed_profile = bool(changed_profile_fields)
        image = data.get("profile_image")
        clear_image = image is False
        replace_image = image and image is not False and image != user.profile_image
        if shared_identity and not actor.is_superuser and (changed_profile or clear_image or replace_image):
            raise ValidationError(
                "This account is shared with another school. Only tenant-specific roles can be changed here."
            )

        previous_image = user.profile_image
        user.email = profile_values["email"]
        user.full_name = profile_values["full_name"]
        user.phone = profile_values["phone"]
        if clear_image:
            user.profile_image = ""
        elif replace_image:
            user.profile_image = image
        user.save(
            update_fields=("email", "full_name", "phone", "profile_image", "updated_at")
        )

        if membership.role != role:
            membership.role = role
            membership.save(update_fields=("role", "updated_at"))

        if previous_image and previous_image.name != getattr(user.profile_image, "name", ""):
            storage, old_name = previous_image.storage, previous_image.name
            transaction.on_commit(lambda: storage.delete(old_name))

        audit.record(
            "tenant.user_updated",
            actor=actor,
            obj=membership,
            tenant=tenant,
            request=request,
            changes={
                "role": {"before": previous_role, "after": role},
                "profile_fields_updated": changed_profile_fields,
                "profile_image_updated": bool(clear_image or replace_image),
            },
            role=role,
            shared_identity=shared_identity,
        )
        return membership


def change_tenant_membership_status(*, tenant, membership_id, action, actor, request=None):
    with transaction.atomic():
        _ensure_actor_can_manage_tenant(actor=actor, tenant=tenant)
        tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
        membership = (
            Membership.objects.select_for_update()
            .select_related("user")
            .get(pk=membership_id, tenant=tenant, **SCHOOL_USER_FILTER)
        )
        if membership.role == Role.OWNER:
            raise ValidationError("The primary school owner cannot be deactivated here.")

        if action == "deactivate" and membership.status == Membership.Status.ACTIVE:
            if membership.role == Role.ADMIN and not Membership.objects.filter(
                tenant=tenant,
                status=Membership.Status.ACTIVE,
                role__in=MANAGEMENT_ROLES,
            ).exclude(pk=membership.pk).exists():
                raise ValidationError("Keep at least one active school administrator.")
            next_status = Membership.Status.SUSPENDED
        elif action == "activate" and membership.status == Membership.Status.SUSPENDED:
            if not membership.user.is_active:
                raise ValidationError("This account is disabled by the platform administrator.")
            next_status = Membership.Status.ACTIVE
        else:
            raise ValidationError("Only active or suspended school accounts can be changed here.")

        previous_status = membership.status
        membership.status = next_status
        membership.save(update_fields=("status", "updated_at"))
        audit.record(
            "tenant.user_status_changed",
            actor=actor,
            obj=membership,
            tenant=tenant,
            request=request,
            changes={"status": {"before": previous_status, "after": next_status}},
            previous_status=previous_status,
            status=next_status,
        )
        return membership


def activate_invited_membership(
    *, tenant, membership_id, user, token, password_form=None, request=None
):
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
        membership = (
            Membership.objects.select_for_update()
            .select_related("user")
            .get(
                pk=membership_id,
                tenant=tenant,
                user_id=user.pk,
                status=Membership.Status.INVITED,
                **SCHOOL_USER_FILTER,
            )
        )
        if not default_token_generator.check_token(membership.user, token):
            raise ValidationError("This activation link has expired or has already been used.")
        if password_form:
            password_form.save(user=membership.user)
        elif not membership.user.has_usable_password():
            raise ValidationError("Set a password before activating this account.")
        if not membership.user.is_active:
            raise ValidationError("This account is disabled by the platform administrator.")

        membership.status = Membership.Status.ACTIVE
        membership.save(update_fields=("status", "updated_at"))
        audit.record(
            "tenant.user_activated",
            actor=membership.user,
            obj=membership,
            tenant=tenant,
            request=request,
            changes={"status": {"before": Membership.Status.INVITED, "after": Membership.Status.ACTIVE}},
            role=membership.role,
        )
        return membership


def reset_tenant_member_password(
    *, tenant, membership_id, user, token, password_form, request=None
):
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
        membership = (
            Membership.objects.select_for_update()
            .select_related("user")
            .get(
                pk=membership_id,
                tenant=tenant,
                user_id=user.pk,
                status__in=(Membership.Status.ACTIVE, Membership.Status.SUSPENDED),
                **SCHOOL_USER_FILTER,
            )
        )
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not default_token_generator.check_token(user, token):
            raise ValidationError("This password reset link has expired or has already been used.")
        password_form.save(user=user)
        audit.record(
            "tenant.user_password_reset",
            actor=user,
            obj=membership,
            tenant=tenant,
            request=request,
            affected_user=user,
        )
        return membership


def ensure_school_admin_can_reset_password(*, tenant, membership, actor):
    if actor.is_superuser:
        return
    _ensure_actor_can_manage_tenant(actor=actor, tenant=tenant)
    if Membership.objects.filter(user=membership.user).exclude(tenant=tenant).exists():
        raise ValidationError(
            "This account is shared with another school. Ask a platform superuser to reset its password."
        )
