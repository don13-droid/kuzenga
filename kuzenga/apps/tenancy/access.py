"""Server-side access enforcement: login -> tenant -> entitlement -> permission."""

from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render

from .models import Module
from .permissions import has_permission
from .services import has_module


def check_access(request, module=None, permission=None):
    """Return None if allowed, otherwise an HttpResponse to send back."""
    if request.tenant is None:
        return redirect("tenancy:select")
    if module and not has_module(request.tenant, module):
        ctx = {"module": Module.objects.filter(code=module).first(), "code": module}
        return render(request, "tenancy/locked.html", ctx, status=403)
    if permission and not has_permission(request.membership, permission):
        return render(request, "tenancy/forbidden.html", status=403)
    return None


def access_required(module=None, permission=None):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"/login/?next={request.path}")
            denied = check_access(request, module, permission)
            if denied is not None:
                return denied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class TenantAccessMixin(LoginRequiredMixin):
    module_code = None
    required_permission = None

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            denied = check_access(request, self.module_code, self.required_permission)
            if denied is not None:
                return denied
        return super().dispatch(request, *args, **kwargs)
