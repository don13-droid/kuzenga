from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.core.context import reset_current_tenant, set_current_tenant

from .models import Membership, Tenant

SESSION_KEY = "active_tenant_id"


def _resolve_membership(request):
    """Tenant comes from the server-side session and is re-validated against an ACTIVE
    membership on every request. A client-supplied tenant id is never trusted on its own."""
    qs = Membership.objects.select_related("tenant").filter(
        user=request.user,
        status=Membership.Status.ACTIVE,
        tenant__status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE],
    )
    tenant_id = request.session.get(SESSION_KEY)
    if tenant_id:
        membership = qs.filter(tenant_id=tenant_id).first()
        if membership:
            return membership
        request.session.pop(SESSION_KEY, None)
    memberships = list(qs[:2])
    if len(memberships) == 1:  # single-school users skip the selector
        request.session[SESSION_KEY] = str(memberships[0].tenant_id)
        return memberships[0]
    return None


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.membership = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            membership = _resolve_membership(request)
            if membership:
                request.membership = membership
                request.tenant = membership.tenant

        if request.tenant is None:
            return self.get_response(request)

        token = set_current_tenant(request.tenant)
        timezone.activate(ZoneInfo(request.tenant.timezone))
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant(token)
            timezone.deactivate()
