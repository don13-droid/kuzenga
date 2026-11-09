from django import forms
from django.contrib.auth import get_user_model

from apps.core.validators import validate_uploaded_image

from .forms import ImagePreviewClearableFileInput
from .models import Membership, Role

EDITABLE_ROLE_CHOICES = tuple((value, label) for value, label in Role.choices if value != Role.OWNER)

USER_INPUT_CLASS = (
    "w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-[#14224a] "
    "outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
)


class TenantMemberForm(forms.Form):
    email = forms.EmailField(label="Email address", max_length=254)
    full_name = forms.CharField(label="Full name", max_length=150, required=False)
    phone = forms.CharField(label="Phone number", max_length=30, required=False)
    role = forms.ChoiceField(choices=EDITABLE_ROLE_CHOICES)
    profile_image = forms.ImageField(
        label="Profile image",
        required=False,
        validators=[validate_uploaded_image],
        widget=ImagePreviewClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )

    def __init__(self, *args, tenant, membership=None, shared_identity=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.membership = membership
        self.shared_identity = shared_identity
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", USER_INPUT_CLASS)

        if membership:
            user = membership.user
            self.initial.update(
                {
                    "email": user.email,
                    "full_name": user.full_name,
                    "phone": user.phone,
                    "role": membership.role,
                    "profile_image": user.profile_image,
                }
            )
            if membership.role == Role.OWNER:
                self.fields["role"].choices = Role.choices
                self.fields["role"].disabled = True
            if shared_identity:
                for name in ("email", "full_name", "phone", "profile_image"):
                    self.fields[name].disabled = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        User = get_user_model()
        existing = User.objects.filter(email__iexact=email)
        if self.membership:
            existing = existing.exclude(pk=self.membership.user_id)
        if self.membership and existing.exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def clean_full_name(self):
        return self.cleaned_data.get("full_name", "").strip()

    def clean_phone(self):
        return self.cleaned_data.get("phone", "").strip()

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")
        if not email or self.membership:
            return cleaned

        User = get_user_model()
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user:
            if existing_user.is_superuser or existing_user.is_staff:
                self.add_error("email", "Platform accounts cannot be added as school users.")
            elif not existing_user.is_active:
                self.add_error("email", "This account is disabled by the platform administrator.")
            elif Membership.objects.filter(user=existing_user, tenant=self.tenant).exists():
                self.add_error("email", "This account already belongs to the selected school.")
        elif not cleaned.get("full_name"):
            self.add_error("full_name", "Enter the user's full name.")
        return cleaned


class InvitationActivationForm(forms.Form):
    confirm = forms.BooleanField(
        label="I accept access to this school account",
        required=True,
    )


class SetAccountPasswordForm(forms.Form):
    password1 = forms.CharField(
        label="New password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "class": USER_INPUT_CLASS}),
    )
    password2 = forms.CharField(
        label="Confirm new password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "class": USER_INPUT_CLASS}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        if password1:
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError

            try:
                validate_password(password1, user=self.user)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self, user=None):
        user = user or self.user
        user.set_password(self.cleaned_data["password1"])
        user.save(update_fields=("password", "updated_at"))
        return user
