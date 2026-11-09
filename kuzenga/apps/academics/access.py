from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.tenancy.access import access_required


def academic_access(permission):
    def decorator(view):
        secured = access_required("academics", permission)(view)

        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.is_authenticated and request.user.is_superuser:
                raise PermissionDenied
            return secured(request, *args, **kwargs)

        return wrapped
    return decorator
