from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, When
from django.utils.html import format_html
from django.utils.text import slugify

from apps.core.validators import validate_uploaded_image

from .models import Membership, Plan, Role, Tenant


class ImagePreviewClearableFileInput(forms.ClearableFileInput):
    def render(self, name, value, attrs=None, renderer=None):
        attrs = self.build_attrs(self.attrs, attrs)
        field_id = attrs.get("id", name)
        rendered_input = super().render(name, value, attrs=attrs, renderer=renderer)
        image_url = ""
        if value:
            try:
                image_url = value.url
            except (AttributeError, ValueError):
                image_url = ""
        preview = format_html(
            '<div class="tenant-image-preview">'
            '<img id="{}_preview" src="{}" data-original-src="{}" '
            'alt="Current image preview"{}></div>',
            field_id,
            image_url,
            image_url,
            " hidden" if not image_url else "",
        )
        return format_html("{}{}", rendered_input, preview)

    class Media:
        css = {"all": ("tenancy/admin/tenant-images.css",)}
        js = ("tenancy/admin/tenant-images.js",)


def primary_administrator_for_tenant(tenant):
    if not tenant.pk:
        return None
    return (
        Membership.objects.filter(
            tenant=tenant,
            status=Membership.Status.ACTIVE,
            role__in=(Role.OWNER, Role.ADMIN),
        )
        .select_related("user")
        .order_by(Case(When(role=Role.OWNER, then=0), default=1, output_field=IntegerField()), "created_at")
        .first()
    )


class TenantAdminForm(forms.ModelForm):
    administrator_full_name = forms.CharField(
        label="Administrator's full name", max_length=150, required=False
    )
    administrator_email = forms.EmailField(label="Email address", required=False)
    administrator_phone = forms.CharField(label="Phone number", max_length=30, required=False)
    administrator_profile_image = forms.ImageField(
        label="Profile image", required=False, validators=[validate_uploaded_image]
    )

    class Meta:
        model = Tenant
        fields = (
            "name",
            "slug",
            "status",
            "timezone",
            "default_currency",
            "country",
            "school_email",
            "school_primary_phone",
            "school_alternative_phone",
            "physical_address",
            "postal_address",
            "website",
            "logo",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.primary_administrator = self._primary_administrator()
        self.fields["logo"].widget = ImagePreviewClearableFileInput()
        self.fields["administrator_profile_image"].widget = ImagePreviewClearableFileInput()
        for image_field in ("logo", "administrator_profile_image"):
            self.fields[image_field].widget.attrs["accept"] = "image/jpeg,image/png,image/webp"
        if self.primary_administrator:
            user = self.primary_administrator.user
            self.fields["administrator_full_name"].required = True
            self.fields["administrator_email"].required = True
            self.initial.update(
                {
                    "administrator_full_name": user.full_name,
                    "administrator_email": user.email,
                    "administrator_phone": user.phone,
                    "administrator_profile_image": user.profile_image,
                }
            )

    def _primary_administrator(self):
        return primary_administrator_for_tenant(self.instance)

    def clean_administrator_full_name(self):
        value = self.cleaned_data.get("administrator_full_name", "").strip()
        if self.primary_administrator and not value:
            raise forms.ValidationError("Enter the primary administrator's full name.")
        return value

    def clean_administrator_email(self):
        value = self.cleaned_data.get("administrator_email", "").strip().lower()
        if not self.primary_administrator:
            return value
        User = get_user_model()
        duplicates = User.objects.filter(email__iexact=value).exclude(
            pk=self.primary_administrator.user_id
        )
        if duplicates.exists():
            raise forms.ValidationError("An account already uses this email address.")
        return value

    def clean_administrator_phone(self):
        return self.cleaned_data.get("administrator_phone", "").strip()


class DashboardForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault(
                "class",
                "w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-[#14224a] "
                "outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100",
            )


class SchoolInformationForm(DashboardForm):
    name = forms.CharField(max_length=200, label="School name")
    code = forms.SlugField(
        max_length=50,
        required=False,
        label="School code",
        help_text="Unique URL-safe tenant identifier. Leave blank to generate it from the school name.",
    )
    country = forms.CharField(
        max_length=2,
        min_length=2,
        initial="ZW",
        help_text="Two-letter country code, for example ZW.",
    )
    timezone = forms.CharField(max_length=64, initial="Africa/Harare")
    default_currency = forms.ChoiceField(choices=Tenant.Currency.choices, initial=Tenant.Currency.USD)

    def clean_name(self):
        value = self.cleaned_data["name"].strip()
        if not value:
            raise ValidationError("Enter the school name.")
        return value

    def clean_code(self):
        code = self.cleaned_data.get("code") or slugify(self.cleaned_data.get("name", ""))
        if not code:
            raise ValidationError("Enter a school code or a school name that can create one.")
        if len(code) > 50:
            raise ValidationError("The generated school code is too long. Enter a shorter code.")
        if Tenant.objects.filter(slug=code).exists():
            raise ValidationError("A tenant with this school code already exists.")
        return code

    def clean_country(self):
        value = self.cleaned_data["country"].strip()
        if not value.isalpha():
            raise ValidationError("Enter a two-letter country code.")
        return value.upper()

    def clean_timezone(self):
        value = self.cleaned_data["timezone"].strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError("Enter a valid IANA time zone, such as Africa/Harare.") from exc
        return value


class AdministratorDetailsForm(DashboardForm):
    first_name = forms.CharField(max_length=75)
    last_name = forms.CharField(max_length=74)
    email = forms.EmailField(label="Email address")

    def clean_first_name(self):
        value = self.cleaned_data["first_name"].strip()
        if not value:
            raise ValidationError("Enter the administrator's first name.")
        return value

    def clean_last_name(self):
        value = self.cleaned_data["last_name"].strip()
        if not value:
            raise ValidationError("Enter the administrator's last name.")
        return value

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account already uses this email address.")
        return email


class SubscriptionConfigurationForm(DashboardForm):
    plan = forms.ModelChoiceField(queryset=Plan.objects.none(), empty_label="Select a plan")
    subscription_start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    subscription_expiry = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    tenant_status = forms.ChoiceField(choices=Tenant.Status.choices, initial=Tenant.Status.ACTIVE)
    academic_year_start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    academic_year_end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = Plan.objects.filter(is_active=True).order_by("name")

    def clean(self):
        cleaned_data = super().clean()
        subscription_start = cleaned_data.get("subscription_start")
        subscription_expiry = cleaned_data.get("subscription_expiry")
        if subscription_start and subscription_expiry and subscription_expiry <= subscription_start:
            self.add_error("subscription_expiry", "Expiry must be after the start date.")

        academic_start = cleaned_data.get("academic_year_start")
        academic_end = cleaned_data.get("academic_year_end")
        if academic_start and academic_end and academic_end <= academic_start:
            self.add_error("academic_year_end", "The academic year end must be after its start.")
        return cleaned_data


class InitialAdministratorPasswordForm(DashboardForm):
    password = forms.CharField(
        label="Initial password",
        strip=False,
        widget=forms.PasswordInput,
        help_text="Set this with the administrator and share it separately through a secure channel.",
    )
    password_confirmation = forms.CharField(
        label="Confirm initial password", strip=False, widget=forms.PasswordInput
    )

    def __init__(self, *args, user_email, full_name, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = get_user_model()(email=user_email, full_name=full_name)

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirmation = cleaned_data.get("password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error("password_confirmation", "The passwords do not match.")
        if password:
            try:
                validate_password(password, user=self.user)
            except ValidationError as exc:
                self.add_error("password", exc)
        return cleaned_data


REGISTRATION_STEPS = (
    (1, "School information"),
    (2, "Administrator"),
    (3, "Subscription & configuration"),
    (4, "Review & create"),
)
