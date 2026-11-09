from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from apps.core import audit
from apps.core.models import AuditEvent


class SchoolAuthenticationForm(AuthenticationForm):
    """Keep platform identities out of the school/client login portal."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_superuser:
            audit.record(
                "authentication.login_failed",
                affected_user=user,
                request=self.request,
                category=AuditEvent.Category.AUTHENTICATION,
                outcome=AuditEvent.Outcome.FAILURE,
                description="Platform account used the school sign-in portal",
            )
            raise ValidationError("Invalid email or password.", code="invalid_login")


class PlatformAuthenticationForm(AuthenticationForm):
    """Only platform superusers may authenticate through the platform portal."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_superuser:
            audit.record(
                "authentication.login_failed",
                affected_user=user,
                request=self.request,
                category=AuditEvent.Category.AUTHENTICATION,
                outcome=AuditEvent.Outcome.FAILURE,
                description="School account used the platform sign-in portal",
            )
            raise ValidationError("Invalid email or password.", code="invalid_login")
