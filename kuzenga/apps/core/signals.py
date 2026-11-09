from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from apps.core import audit
from apps.core.models import AuditEvent


def _known_user_from_failed_credentials(credentials):
    identifier = credentials.get("username") or credentials.get("email")
    if not isinstance(identifier, str) or not identifier:
        return None
    return get_user_model().objects.filter(email__iexact=identifier[:254]).first()


def _single_membership_tenant(user):
    if user is None or user.is_superuser:
        return None
    from apps.tenancy.models import Membership, Tenant

    memberships = list(
        Membership.objects.filter(
            user=user,
            status=Membership.Status.ACTIVE,
            tenant__status__in=(Tenant.Status.ACTIVE, Tenant.Status.TRIAL),
        ).select_related("tenant")[:2]
    )
    return memberships[0].tenant if len(memberships) == 1 else None


@receiver(user_logged_in, dispatch_uid="kuzenga.audit.user_logged_in")
def record_login_success(sender, request, user, **kwargs):
    audit.record(
        "authentication.login_succeeded",
        actor=user,
        affected_user=user,
        tenant=getattr(request, "tenant", None) or _single_membership_tenant(user),
        request=request,
        category=AuditEvent.Category.AUTHENTICATION,
    )


@receiver(user_login_failed, dispatch_uid="kuzenga.audit.user_login_failed")
def record_login_failure(sender, credentials, request=None, **kwargs):
    target_user = _known_user_from_failed_credentials(credentials)
    audit.record(
        "authentication.login_failed",
        actor=None,
        affected_user=target_user,
        tenant=getattr(request, "tenant", None) or _single_membership_tenant(target_user),
        request=request,
        category=AuditEvent.Category.AUTHENTICATION,
        outcome=AuditEvent.Outcome.FAILURE,
    )


@receiver(user_logged_out, dispatch_uid="kuzenga.audit.user_logged_out")
def record_logout(sender, request, user, **kwargs):
    audit.record(
        "authentication.logout",
        actor=user,
        affected_user=user,
        tenant=getattr(request, "tenant", None) or _single_membership_tenant(user),
        request=request,
        category=AuditEvent.Category.AUTHENTICATION,
    )
