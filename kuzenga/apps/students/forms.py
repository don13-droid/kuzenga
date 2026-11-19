from django import forms
from django.contrib.auth import get_user_model

from apps.academics.models import AcademicYear, ClassGroup
from apps.core.context import get_current_tenant
from apps.core.forms import TenantModelForm
from apps.tenancy.models import Membership, Role

from .models import Guardian, Student, StudentDocument
from .services import can_manage_portal_links

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class StudentForm(TenantModelForm):
    admission_number = forms.CharField(max_length=30, required=False, help_text="Leave blank to generate a school admission number.")
    class_group = forms.ModelChoiceField(
        queryset=ClassGroup.objects.all(), required=False, label="Initial class (optional)"
    )

    class Meta:
        model = Student
        fields = ["admission_number", "first_name", "last_name", "preferred_name", "date_of_birth", "gender", "profile_image", "portal_user"]
        widgets = {"date_of_birth": DATE}

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = get_current_tenant()
        self.can_manage_portal_links = can_manage_portal_links(actor, tenant)
        if self.can_manage_portal_links:
            used = Student.objects.exclude(pk=self.instance.pk).filter(
                portal_user__isnull=False
            ).values("portal_user_id")
            self.fields["portal_user"].queryset = get_user_model().objects.filter(
                memberships__tenant=tenant, memberships__role=Role.STUDENT,
                memberships__status=Membership.Status.ACTIVE, is_active=True,
                is_staff=False, is_superuser=False,
            ).exclude(pk__in=used).order_by("email")
            self.fields["portal_user"].label = "Student login account (optional)"
            self.fields["portal_user"].help_text = (
                "Create and activate a Student account in Users & staff first, then select it here. "
                "Leave blank to keep this record without portal access."
            )
        else:
            self.fields.pop("portal_user")
        if not self.instance._state.adding:
            self.fields.pop("class_group")
            self.fields["admission_number"].disabled = True
            self.fields["admission_number"].help_text = "The admission number is preserved when editing."

    def clean(self):
        data = super().clean()
        if "portal_user" in self.data and not self.can_manage_portal_links:
            raise forms.ValidationError("Only a school owner or administrator can link student login accounts.")
        if (self.can_manage_portal_links and self.instance.pk
                and "portal_user" not in self.data):
            data["portal_user"] = self.instance.portal_user
        dob, first, last = data.get("date_of_birth"), data.get("first_name"), data.get("last_name")
        if (
            dob
            and first
            and last
            and Student.objects.filter(
                first_name__iexact=first, last_name__iexact=last, date_of_birth=dob
            ).exclude(pk=self.instance.pk).exists()
        ):
            raise forms.ValidationError(
                "A learner with the same name and date of birth already exists."
            )
        return data


class EnrolForm(forms.Form):
    class_group = forms.ModelChoiceField(queryset=ClassGroup.objects.all())
    effective_from = forms.DateField(
        required=False, widget=DATE, label="Effective from (default: today)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["class_group"].queryset = ClassGroup.objects.all()


class GuardianForm(TenantModelForm):
    guardian = forms.ModelChoiceField(queryset=Guardian.objects.all(), required=False, label="Existing guardian (optional)")
    relationship = forms.CharField(max_length=50, required=False)
    is_primary = forms.BooleanField(required=False, label="Primary contact")
    can_collect = forms.BooleanField(required=False, label="Authorised to collect")
    is_emergency = forms.BooleanField(required=False, label="Emergency contact")

    class Meta:
        model = Guardian
        fields = ["first_name", "last_name", "phone", "email"]

    def __init__(self, *args, optional=False, **kwargs):
        self.optional = optional
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = False
        self.fields["last_name"].required = False

    def clean(self):
        data = super().clean()
        existing = data.get("guardian")
        supplied = any(data.get(key) for key in ("first_name", "last_name", "phone", "email", "relationship", "is_primary", "is_emergency", "can_collect"))
        if self.optional and not existing and not supplied:
            return data
        if existing:
            if any(data.get(key) for key in ("first_name", "last_name", "phone", "email")):
                raise forms.ValidationError("Choose an existing guardian or enter a new guardian's details.")
            phone, email = existing.phone, existing.email
        else:
            if not data.get("first_name") or not data.get("last_name"):
                raise forms.ValidationError("Enter both guardian names or choose an existing guardian.")
            phone, email = data.get("phone"), data.get("email")
        if (data.get("is_primary") or data.get("is_emergency")) and not (phone or email):
            raise forms.ValidationError("Primary and emergency contacts need a phone number or email.")
        return data

    @property
    def has_contact(self):
        return bool(self.cleaned_data.get("guardian") or self.cleaned_data.get("first_name"))


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=Student.Status.choices)
    reason = forms.CharField(max_length=255, help_text="Explain the change; avoid unnecessary personal information.")


class DocumentForm(TenantModelForm):
    class Meta:
        model = StudentDocument
        fields = ["title", "file"]


class DirectoryFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=150, label="Name or admission number")
    class_group = forms.ModelChoiceField(queryset=ClassGroup.objects.all(), required=False)
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.all(), required=False)
    status = forms.ChoiceField(choices=[("", "All statuses"), *Student.Status.choices], required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["class_group"].queryset = ClassGroup.objects.all()
        self.fields["academic_year"].queryset = AcademicYear.objects.all()

