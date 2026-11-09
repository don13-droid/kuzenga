from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.tenancy.models import Membership, Role, Tenant
from apps.tenancy.permissions import ROLE_PERMISSIONS, has_permission

from .user_admin_forms import (
    InvitationActivationForm,
    SetAccountPasswordForm,
    TenantMemberForm,
)
from .user_admin_services import (
    SCHOOL_USER_FILTER,
    activate_invited_membership,
    change_tenant_membership_status,
    create_tenant_member,
    ensure_school_admin_can_reset_password,
    get_tenant_membership,
    reset_tenant_member_password,
    tenant_memberships,
    update_tenant_member,
)

PLATFORM_LINKS = {
    "directory": "superuser:tenant-users",
    "create": "superuser:tenant-user-create",
    "roles": "superuser:tenant-user-roles",
    "profile": "superuser:tenant-user-profile",
    "edit": "superuser:tenant-user-edit",
    "status": "superuser:tenant-user-status",
    "invite": "superuser:tenant-user-invite",
    "reset": "superuser:tenant-user-password-reset",
}
SCHOOL_LINKS = {
    "directory": "tenancy:users",
    "create": "tenancy:user-create",
    "roles": "tenancy:user-roles",
    "profile": "tenancy:user-profile",
    "edit": "tenancy:user-edit",
    "status": "tenancy:user-status",
    "invite": "tenancy:user-invite",
    "reset": "tenancy:user-password-reset",
}
ACCOUNT_ACTIVATION_URL = "tenant-user-activate"
ACCOUNT_PASSWORD_RESET_URL = "tenant-user-password-reset-confirm"
PERMISSION_LABELS = {
    "academics.view": "View academic setup",
    "academics.manage": "Manage academic setup",
    "students.view": "View students",
    "students.manage": "Manage students",
    "admissions.view": "View school admissions",
    "admissions.manage": "Manage applications and supporting documents",
    "admissions.review": "Review applications and record decisions",
    "admissions.enrol": "Enrol accepted applicants",
    "attendance.view": "View attendance",
    "attendance.take_register": "Take class attendance",
    "users.view": "View school users",
    "users.manage": "Manage school users and roles",
}


def _platform_route(view):
    @wraps(view)
    def wrapped(request, tenant_id, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), login_url=reverse("platform-login")
            )
        if not request.user.is_superuser:
            raise PermissionDenied
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        return view(
            request,
            tenant,
            *args,
            is_platform=True,
            base_template="superuser/base.html",
            **kwargs,
        )

    return wrapped


def _school_route(permission):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), login_url=reverse("login"))
            tenant = getattr(request, "tenant", None)
            if tenant is None:
                return redirect("tenancy:select")
            if not has_permission(getattr(request, "membership", None), permission):
                raise PermissionDenied
            return view(
                request,
                *args,
                tenant=tenant,
                is_platform=False,
                base_template="base/base.html",
                **kwargs,
            )

        return wrapped

    return decorate


def _reverse(scope, key, tenant, membership=None):
    name = (PLATFORM_LINKS if scope else SCHOOL_LINKS)[key]
    if scope:
        args = [tenant.pk]
        if membership is not None:
            args.append(membership.pk)
    else:
        args = [membership.pk] if membership is not None else []
    return reverse(name, args=args)


def _membership_status_label(membership):
    if not membership.user.is_active:
        return "Platform disabled"
    return dict(Membership.Status.choices).get(membership.status, membership.status.title())


def _directory_context(request, tenant, *, is_platform, base_template):
    queryset = tenant_memberships(tenant)
    search = request.GET.get("q", "").strip()
    if search:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(user__full_name__icontains=search)
            | Q(user__email__icontains=search)
            | Q(user__phone__icontains=search)
        )

    role = request.GET.get("role", "")
    if role in Role.values:
        queryset = queryset.filter(role=role)
    group = request.GET.get("group", "")
    if not role:
        if group == "administrators":
            queryset = queryset.filter(role__in=(Role.OWNER, Role.ADMIN))
        elif group == "teachers":
            queryset = queryset.filter(role=Role.TEACHER)
        elif group == "non-teaching":
            queryset = queryset.filter(role__in=(Role.BURSAR, Role.HOD, Role.STAFF))
    status = request.GET.get("status", "")
    if status in Membership.Status.values:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset.order_by("user__full_name", "user__email", "pk"), 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    can_manage = is_platform or has_permission(request.membership, "users.manage")
    rows = []
    for membership in page_obj.object_list:
        rows.append(
            {
                "membership": membership,
                "status_label": _membership_status_label(membership),
                "profile_url": _reverse(is_platform, "profile", tenant, membership),
                "edit_url": _reverse(is_platform, "edit", tenant, membership),
                "status_url": _reverse(is_platform, "status", tenant, membership),
                "invite_url": _reverse(is_platform, "invite", tenant, membership),
                "reset_url": _reverse(is_platform, "reset", tenant, membership),
                "can_toggle": can_manage
                and membership.role != Role.OWNER
                and membership.status in (Membership.Status.ACTIVE, Membership.Status.SUSPENDED)
                and membership.user.is_active,
            }
        )

    school_users = tenant_memberships(tenant)
    return {
        "tenant": tenant,
        "base_template": base_template,
        "is_platform": is_platform,
        "can_manage": can_manage,
        "rows": rows,
        "page_obj": page_obj,
        "search": search,
        "selected_role": role,
        "selected_group": group,
        "selected_status": status,
        "role_choices": Role.choices,
        "status_choices": Membership.Status.choices,
        "counts": {
            "total": school_users.count(),
            "administrators": school_users.filter(role__in=(Role.OWNER, Role.ADMIN)).count(),
            "teachers": school_users.filter(role=Role.TEACHER).count(),
            "staff": school_users.filter(role__in=(Role.BURSAR, Role.HOD, Role.STAFF)).count(),
        },
        "directory_url": _reverse(is_platform, "directory", tenant),
        "create_url": _reverse(is_platform, "create", tenant),
        "roles_url": _reverse(is_platform, "roles", tenant),
        "active_section": "tenant-users" if is_platform else "users",
    }


@_platform_route
@require_GET
def platform_user_directory(request, tenant, *, is_platform, base_template):
    context = _directory_context(request, tenant, is_platform=is_platform, base_template=base_template)
    context["title"] = "Tenant User Directory"
    return render(request, "tenancy/user_admin/directory.html", context)


@_school_route("users.view")
@require_GET
def school_user_directory(request, tenant, *, is_platform, base_template):
    context = _directory_context(request, tenant, is_platform=is_platform, base_template=base_template)
    context["title"] = "User Directory"
    return render(request, "tenancy/user_admin/directory.html", context)


def _create_member(request, tenant, *, is_platform, base_template):
    initial_role = request.GET.get("role", Role.ADMIN)
    if initial_role not in Role.values or initial_role == Role.OWNER:
        initial_role = Role.ADMIN
    form = TenantMemberForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        tenant=tenant,
        initial={"role": initial_role},
    )
    if request.method == "POST" and form.is_valid():
        try:
            membership, new_account = create_tenant_member(
                tenant=tenant,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            uid = urlsafe_base64_encode(str(membership.user.pk).encode())
            token = default_token_generator.make_token(membership.user)
            activation_path = reverse(
                ACCOUNT_ACTIVATION_URL,
                args=[tenant.pk, membership.pk, uid, token],
            )
            return render(
                request,
                "tenancy/user_admin/invitation_created.html",
                {
                    "tenant": tenant,
                    "base_template": base_template,
                    "membership": membership,
                    "new_account": new_account,
                    "activation_url": request.build_absolute_uri(activation_path),
                    "directory_url": _reverse(is_platform, "directory", tenant),
                },
            )

    return render(
        request,
        "tenancy/user_admin/form.html",
        {
            "tenant": tenant,
            "base_template": base_template,
            "form": form,
            "title": "Add school user",
            "directory_url": _reverse(is_platform, "directory", tenant),
            "form_action": request.path,
            "shared_identity": False,
            "primary_owner": False,
            "active_section": "tenant-users" if is_platform else "users",
        },
        status=400 if request.method == "POST" and not form.is_valid() else 200,
    )


@_platform_route
@require_http_methods(["GET", "POST"])
def platform_user_create(request, tenant, *, is_platform, base_template):
    return _create_member(request, tenant, is_platform=is_platform, base_template=base_template)


@_school_route("users.manage")
@require_http_methods(["GET", "POST"])
def school_user_create(request, tenant, *, is_platform, base_template):
    return _create_member(request, tenant, is_platform=is_platform, base_template=base_template)


def _role_permissions():
    permissions = []
    for role, label in Role.choices:
        granted = ROLE_PERMISSIONS.get(role, set())
        if "*" in granted:
            role_permissions = ["All school-level permissions (platform administration excluded)"]
        else:
            role_permissions = [
                PERMISSION_LABELS.get(permission, permission)
                for permission in sorted(granted)
            ] or ["No additional permissions"]
        permissions.append({"role": role, "label": label, "permissions": role_permissions})
    return permissions


def _roles_page(request, tenant, *, is_platform, base_template):
    return render(
        request,
        "tenancy/user_admin/roles.html",
        {
            "tenant": tenant,
            "base_template": base_template,
            "roles": _role_permissions(),
            "directory_url": _reverse(is_platform, "directory", tenant),
            "active_section": "tenant-users" if is_platform else "users",
        },
    )


@_platform_route
@require_GET
def platform_user_roles(request, tenant, *, is_platform, base_template):
    return _roles_page(request, tenant, is_platform=is_platform, base_template=base_template)


@_school_route("users.view")
@require_GET
def school_user_roles(request, tenant, *, is_platform, base_template):
    return _roles_page(request, tenant, is_platform=is_platform, base_template=base_template)


def _profile_context(request, tenant, membership, *, is_platform, base_template):
    can_manage = is_platform or has_permission(request.membership, "users.manage")
    user = membership.user
    return {
        "tenant": tenant,
        "base_template": base_template,
        "membership": membership,
        "user_record": user,
        "status_label": _membership_status_label(membership),
        "can_manage": can_manage,
        "shared_identity": Membership.objects.filter(user=user).exclude(tenant=tenant).exists(),
        "directory_url": _reverse(is_platform, "directory", tenant),
        "edit_url": _reverse(is_platform, "edit", tenant, membership),
        "status_url": _reverse(is_platform, "status", tenant, membership),
        "invite_url": _reverse(is_platform, "invite", tenant, membership),
        "reset_url": _reverse(is_platform, "reset", tenant, membership),
        "active_section": "tenant-users" if is_platform else "users",
    }


def _get_member_or_404(tenant, membership_id):
    membership = get_tenant_membership(tenant, membership_id)
    if membership is None:
        raise Http404
    return membership


@_platform_route
@require_GET
def platform_user_profile(request, tenant, membership_id, *, is_platform, base_template):
    membership = _get_member_or_404(tenant, membership_id)
    return render(
        request,
        "tenancy/user_admin/profile.html",
        _profile_context(request, tenant, membership, is_platform=is_platform, base_template=base_template),
    )


@_school_route("users.view")
@require_GET
def school_user_profile(request, membership_id, *, tenant, is_platform, base_template):
    membership = _get_member_or_404(tenant, membership_id)
    return render(
        request,
        "tenancy/user_admin/profile.html",
        _profile_context(request, tenant, membership, is_platform=is_platform, base_template=base_template),
    )


def _edit_member(request, tenant, membership, *, is_platform, base_template):
    shared_identity = Membership.objects.filter(user=membership.user).exclude(tenant=tenant).exists()
    form = TenantMemberForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        tenant=tenant,
        membership=membership,
        shared_identity=shared_identity and not request.user.is_superuser,
    )
    if request.method == "POST" and form.is_valid():
        try:
            membership = update_tenant_member(
                tenant=tenant,
                membership_id=membership.pk,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "User details were saved.")
            return redirect(_reverse(is_platform, "profile", tenant, membership))

    return render(
        request,
        "tenancy/user_admin/form.html",
        {
            "tenant": tenant,
            "base_template": base_template,
            "membership": membership,
            "form": form,
            "title": "Edit user",
            "directory_url": _reverse(is_platform, "directory", tenant),
            "profile_url": _reverse(is_platform, "profile", tenant, membership),
            "form_action": request.path,
            "shared_identity": shared_identity,
            "primary_owner": membership.role == Role.OWNER,
            "active_section": "tenant-users" if is_platform else "users",
        },
        status=400 if request.method == "POST" and not form.is_valid() else 200,
    )


@_platform_route
@require_http_methods(["GET", "POST"])
def platform_user_edit(request, tenant, membership_id, *, is_platform, base_template):
    return _edit_member(
        request,
        tenant,
        _get_member_or_404(tenant, membership_id),
        is_platform=is_platform,
        base_template=base_template,
    )


@_school_route("users.manage")
@require_http_methods(["GET", "POST"])
def school_user_edit(request, membership_id, *, tenant, is_platform, base_template):
    return _edit_member(
        request,
        tenant,
        _get_member_or_404(tenant, membership_id),
        is_platform=is_platform,
        base_template=base_template,
    )


def _change_member_status(request, tenant, membership, *, is_platform):
    try:
        membership = change_tenant_membership_status(
            tenant=tenant,
            membership_id=membership.pk,
            action=request.POST.get("action", ""),
            actor=request.user,
            request=request,
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"{membership.user.get_full_name()} account status was updated.")
    return redirect(_reverse(is_platform, "profile", tenant, membership))


@_platform_route
@require_POST
def platform_user_status(request, tenant, membership_id, *, is_platform, base_template):
    return _change_member_status(
        request, tenant, _get_member_or_404(tenant, membership_id), is_platform=is_platform
    )


@_school_route("users.manage")
@require_POST
def school_user_status(request, membership_id, *, tenant, is_platform, base_template):
    return _change_member_status(
        request, tenant, _get_member_or_404(tenant, membership_id), is_platform=is_platform
    )


def _render_secure_link(request, tenant, membership, *, kind, base_template):
    uid = urlsafe_base64_encode(str(membership.user.pk).encode())
    token = default_token_generator.make_token(membership.user)
    url_name = ACCOUNT_ACTIVATION_URL if kind == "activation" else ACCOUNT_PASSWORD_RESET_URL
    path = reverse(url_name, args=[tenant.pk, membership.pk, uid, token])
    return render(
        request,
        "tenancy/user_admin/secure_link.html",
        {
            "tenant": tenant,
            "base_template": base_template,
            "membership": membership,
            "kind": kind,
            "secure_url": request.build_absolute_uri(path),
            "directory_url": _reverse(request.user.is_superuser, "directory", tenant),
        },
    )


def _issue_invitation(request, tenant, membership, *, base_template):
    if membership.status != Membership.Status.INVITED:
        messages.error(request, "Only pending invitations can be reissued.")
        return redirect(_reverse(request.user.is_superuser, "profile", tenant, membership))
    from apps.core import audit

    audit.record(
        "tenant.user_invitation_link_issued",
        actor=request.user,
        obj=membership,
        tenant=tenant,
        request=request,
    )
    return _render_secure_link(
        request, tenant, membership, kind="activation", base_template=base_template
    )


@_platform_route
@require_POST
def platform_user_invite(request, tenant, membership_id, *, is_platform, base_template):
    return _issue_invitation(
        request,
        tenant,
        _get_member_or_404(tenant, membership_id),
        base_template=base_template,
    )


@_school_route("users.manage")
@require_POST
def school_user_invite(request, membership_id, *, tenant, is_platform, base_template):
    return _issue_invitation(
        request,
        tenant,
        _get_member_or_404(tenant, membership_id),
        base_template=base_template,
    )


def _issue_password_reset(request, tenant, membership, *, base_template):
    try:
        ensure_school_admin_can_reset_password(
            tenant=tenant,
            membership=membership,
            actor=request.user,
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect(_reverse(request.user.is_superuser, "profile", tenant, membership))
    if membership.status == Membership.Status.INVITED:
        messages.error(request, "Use the account activation link for a pending invitation.")
        return redirect(_reverse(request.user.is_superuser, "profile", tenant, membership))
    from apps.core import audit

    audit.record(
        "tenant.user_password_reset_link_issued",
        actor=request.user,
        obj=membership,
        tenant=tenant,
        request=request,
    )
    return _render_secure_link(
        request, tenant, membership, kind="password_reset", base_template=base_template
    )


@_platform_route
@require_POST
def platform_user_password_reset(request, tenant, membership_id, *, is_platform, base_template):
    return _issue_password_reset(
        request,
        tenant,
        _get_member_or_404(tenant, membership_id),
        base_template=base_template,
    )


@_school_route("users.manage")
@require_POST
def school_user_password_reset(request, membership_id, *, tenant, is_platform, base_template):
    return _issue_password_reset(
        request,
        tenant,
        _get_member_or_404(tenant, membership_id),
        base_template=base_template,
    )


def _decode_token_user(tenant_id, membership_id, uidb64, token, *, reset=False):
    User = get_user_model()
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=user_id, is_superuser=False, is_staff=False, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        raise Http404 from None
    if not default_token_generator.check_token(user, token):
        raise Http404

    statuses = (
        (Membership.Status.ACTIVE, Membership.Status.SUSPENDED)
        if reset
        else (Membership.Status.INVITED,)
    )
    membership = Membership.objects.filter(
        pk=membership_id,
        tenant_id=tenant_id,
        user=user,
        status__in=statuses,
        **SCHOOL_USER_FILTER,
    ).select_related("tenant", "user").first()
    if membership is None:
        raise Http404
    return membership


@require_http_methods(["GET", "POST"])
def activate_tenant_member(request, tenant_id, membership_id, uidb64, token):
    membership = _decode_token_user(tenant_id, membership_id, uidb64, token)
    user = membership.user
    password_form = None
    activation_form = None
    if user.has_usable_password():
        activation_form = InvitationActivationForm(request.POST if request.method == "POST" else None)
        valid = activation_form.is_valid()
    else:
        password_form = SetAccountPasswordForm(
            request.POST if request.method == "POST" else None,
            user=user,
        )
        valid = password_form.is_valid()

    if request.method == "POST" and valid:
        try:
            membership = activate_invited_membership(
                tenant=membership.tenant,
                membership_id=membership.pk,
                user=user,
                token=token,
                password_form=password_form,
                request=request,
            )
        except ValidationError as exc:
            if password_form:
                password_form.add_error(None, exc)
            else:
                activation_form.add_error(None, exc)
        else:
            return render(
                request,
                "tenancy/user_admin/account_complete.html",
                {"tenant": membership.tenant, "action": "activated"},
            )

    form = password_form or activation_form
    return render(
        request,
        "tenancy/user_admin/activate.html",
        {"tenant": membership.tenant, "membership": membership, "form": form},
        status=400 if request.method == "POST" and not form.is_valid() else 200,
    )


@require_http_methods(["GET", "POST"])
def reset_tenant_member_password_view(request, tenant_id, membership_id, uidb64, token):
    membership = _decode_token_user(tenant_id, membership_id, uidb64, token, reset=True)
    form = SetAccountPasswordForm(
        request.POST if request.method == "POST" else None,
        user=membership.user,
    )
    if request.method == "POST" and form.is_valid():
        try:
            reset_tenant_member_password(
                tenant=membership.tenant,
                membership_id=membership.pk,
                user=membership.user,
                token=token,
                password_form=form,
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return render(
                request,
                "tenancy/user_admin/account_complete.html",
                {"tenant": membership.tenant, "action": "password_reset"},
            )

    return render(
        request,
        "tenancy/user_admin/password_reset.html",
        {"tenant": membership.tenant, "membership": membership, "form": form},
        status=400 if request.method == "POST" and not form.is_valid() else 200,
    )
