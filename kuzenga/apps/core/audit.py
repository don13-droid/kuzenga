import ipaddress
from datetime import date, datetime
from uuid import UUID

from django.contrib.auth import get_user_model

from .context import get_current_tenant
from .models import AuditEvent

SENSITIVE_PARTS = (
    "password",
    "token",
    "secret",
    "session",
    "credential",
    "authorization",
    "cookie",
    "email",
    "phone",
    "address",
    "profile_image",
    "image",
    "full_name",
    "first_name",
    "last_name",
)

ACTION_CATEGORIES = {
    "tenant.created": AuditEvent.Category.TENANT,
    "tenant.profile_updated": AuditEvent.Category.TENANT,
    "tenant.status_changed": AuditEvent.Category.TENANT,
    "tenant.configuration_changed": AuditEvent.Category.CONFIGURATION,
}

ACTION_DESCRIPTIONS = {
    "tenant.created": "Tenant registered",
    "tenant.profile_updated": "Tenant profile updated",
    "tenant.status_changed": "Tenant status changed",
    "tenant.configuration_changed": "Tenant configuration updated",
    "tenant.user_invited": "School user account created or invited",
    "tenant.user_updated": "School user profile or role updated",
    "tenant.user_status_changed": "School user access status changed",
    "tenant.user_activated": "School user activated their account",
    "tenant.user_password_reset_link_issued": "Password reset link issued",
    "tenant.user_password_reset": "User completed a password reset",
    "tenant.user_invitation_link_issued": "Account activation link reissued",
    "tenant.membership_created": "School membership created",
    "tenant.membership_deleted": "School membership removed",
    "user.created": "User account created",
    "user.profile_updated": "User profile updated",
    "user.status_changed": "Platform user account status changed",
    "user.password_reset_completed": "Platform administrator reset the account password",
    "security.platform_privilege_changed": "Platform privileges changed",
    "subscription.created": "Subscription record created",
    "subscription.updated": "Subscription details updated",
    "entitlement.updated": "Tenant module access updated",
    "subscription.activated": "Subscription activated",
    "subscription.suspended": "Subscription suspended",
    "entitlement.granted": "Tenant module access granted",
    "authentication.login_succeeded": "Signed in successfully",
    "authentication.login_failed": "Failed sign-in attempt",
    "authentication.logout": "Signed out",
}


def category_for_action(action):
    if action in ACTION_CATEGORIES:
        return ACTION_CATEGORIES[action]
    if action.startswith("authentication."):
        return AuditEvent.Category.AUTHENTICATION
    if action.startswith(("tenant.user", "tenant.membership")):
        return AuditEvent.Category.USER
    if action.startswith("user."):
        return AuditEvent.Category.USER
    if action.startswith(("tenant.configuration", "configuration.")):
        return AuditEvent.Category.CONFIGURATION
    if action.startswith(("subscription.", "entitlement.")):
        return AuditEvent.Category.SUBSCRIPTION
    if action.startswith("security."):
        return AuditEvent.Category.SECURITY
    if action.startswith("tenant."):
        return AuditEvent.Category.TENANT
    return AuditEvent.Category.OTHER


def is_sensitive_key(key):
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_PARTS)


def _json_safe(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value[:512] if isinstance(value, str) else value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key)[:100]: "[REDACTED]" if is_sensitive_key(key) else _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "_meta") and hasattr(value, "pk"):
        return str(value.pk)
    if hasattr(value, "name") and hasattr(value, "storage"):
        return {"present": bool(value)}
    return str(value)[:512]


def form_changes(form, *, masked_fields=()):
    """Return before/after values for changed fields, redacting sensitive/personal data."""
    changes = {}
    masked = set(masked_fields)
    for field_name in form.changed_data:
        if field_name in masked or is_sensitive_key(field_name):
            changes[field_name] = "[REDACTED]"
            continue
        changes[field_name] = {
            "before": _json_safe(form.initial.get(field_name)),
            "after": _json_safe(form.cleaned_data.get(field_name)),
        }
    return changes


def _target_user(obj):
    User = get_user_model()
    if isinstance(obj, User):
        return obj
    related_user = getattr(obj, "user", None)
    return related_user if isinstance(related_user, User) else None


def _request_details(request):
    if request is None:
        return {}
    remote_addr = request.META.get("REMOTE_ADDR", "")
    try:
        ip_address = str(ipaddress.ip_address(remote_addr)) if remote_addr else None
    except ValueError:
        ip_address = None
    resolver_match = getattr(request, "resolver_match", None)
    return {
        "ip_address": ip_address,
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:512],
        "request_method": (getattr(request, "method", "") or "")[:10],
        # Store the named route, never a path that could contain an auth token.
        "request_route": (getattr(resolver_match, "view_name", "") or "")[:150],
    }


def record(
    action,
    *,
    actor=None,
    obj=None,
    tenant=None,
    request=None,
    affected_user=None,
    category=None,
    description="",
    outcome=AuditEvent.Outcome.SUCCESS,
    changes=None,
    **metadata,
):
    tenant = tenant or getattr(request, "tenant", None) or get_current_tenant()
    safe_metadata = {
        str(key)[:100]: "[REDACTED]" if is_sensitive_key(key) else str(value)[:512]
        for key, value in metadata.items()
    }
    return AuditEvent.objects.create(
        tenant=tenant,
        actor=actor if (actor is not None and actor.pk) else None,
        target_user=affected_user or _target_user(obj),
        action=action,
        category=category or category_for_action(action),
        description=(
            description
            or ACTION_DESCRIPTIONS.get(action)
            or action.replace(".", " ").replace("_", " ").capitalize()
        )[:255],
        outcome=outcome,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        metadata=safe_metadata,
        changes=_json_safe(changes or {}),
        **_request_details(request),
    )
