import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.core.exceptions import ValidationError

from apps.academics.models import (
    AcademicYear,
    AssessmentCategory,
    ClassGroup,
    Department,
    Grade,
    GradeBoundary,
    SchoolCalendarEvent,
    Subject,
    Term,
)

from .forms import ImagePreviewClearableFileInput
from .models import Tenant, TenantConfiguration

INPUT_CLASS = (
    "w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-[#14224a] "
    "outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                field.widget.attrs.setdefault("class", INPUT_CLASS)
            if field.help_text:
                field.widget.attrs.setdefault("aria-describedby", f"id_{name}_helptext")


class TenantIdentityForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Tenant
        fields = (
            "name",
            "school_email",
            "school_primary_phone",
            "school_alternative_phone",
            "physical_address",
            "postal_address",
            "website",
            "logo",
        )
        widgets = {
            "physical_address": forms.Textarea(attrs={"rows": 3}),
            "postal_address": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["logo"].widget = ImagePreviewClearableFileInput(
            attrs={"accept": "image/jpeg,image/png,image/webp"}
        )


class RegionalConfigurationForm(StyledFormMixin, forms.Form):
    DATE_FORMATS = (("d/m/Y", "DD/MM/YYYY"), ("m/d/Y", "MM/DD/YYYY"), ("Y-m-d", "YYYY-MM-DD"))
    country = forms.CharField(max_length=2, min_length=2)
    default_currency = forms.ChoiceField(choices=Tenant.Currency.choices)
    timezone = forms.CharField(max_length=64)
    date_format = forms.ChoiceField(choices=DATE_FORMATS)
    language = forms.CharField(max_length=12, initial="en")
    measurement_system = forms.ChoiceField(choices=TenantConfiguration.MeasurementSystem.choices)

    def __init__(self, *args, tenant, configuration, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.configuration = configuration
        if not self.is_bound:
            self.initial.update(
                {
                    "country": tenant.country,
                    "default_currency": tenant.default_currency,
                    "timezone": tenant.timezone,
                    "date_format": configuration.date_format,
                    "language": configuration.language,
                    "measurement_system": configuration.measurement_system,
                }
            )

    def clean_country(self):
        country = self.cleaned_data["country"].strip().upper()
        if not country.isalpha():
            raise ValidationError("Enter a two-letter country code.")
        return country

    def clean_timezone(self):
        timezone = self.cleaned_data["timezone"].strip()
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError("Enter a valid IANA time zone, such as Africa/Harare.") from exc
        return timezone

    def clean_language(self):
        language = self.cleaned_data["language"].strip()
        if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", language):
            raise ValidationError("Use a language tag such as en or en-ZW.")
        return language


class TenantOwnedModelForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.instance.tenant = tenant
        for field in self.fields.values():
            if isinstance(field, forms.ModelChoiceField):
                related_model = field.queryset.model
                field.queryset = related_model.unscoped.filter(tenant=tenant)


class AcademicYearConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = AcademicYear
        fields = ("name", "start_date", "end_date", "status", "is_current")
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}), "end_date": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end:
            overlaps = AcademicYear.unscoped.filter(
                tenant=self.tenant, start_date__lte=end, end_date__gte=start
            ).exclude(pk=self.instance.pk)
            if overlaps.exists():
                self.add_error("start_date", "Academic years may not overlap.")
        if cleaned.get("is_current") and cleaned.get("status") == AcademicYear.Status.CLOSED:
            self.add_error("is_current", "A closed academic year cannot be marked current.")
        return cleaned


class TermConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = Term
        fields = ("academic_year", "name", "start_date", "end_date")
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}), "end_date": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        cleaned = super().clean()
        year, start, end = (
            cleaned.get("academic_year"),
            cleaned.get("start_date"),
            cleaned.get("end_date"),
        )
        if year and start and end:
            overlaps = Term.unscoped.filter(
                tenant=self.tenant,
                academic_year=year,
                start_date__lte=end,
                end_date__gte=start,
            ).exclude(pk=self.instance.pk)
            if overlaps.exists():
                self.add_error("start_date", "Terms in the same academic year may not overlap.")
        return cleaned


class CalendarEventConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = SchoolCalendarEvent
        fields = ("academic_year", "title", "kind", "start_date", "end_date", "notes")
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}), "end_date": forms.DateInput(attrs={"type": "date"})}


class GradeConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = Grade
        fields = ("name", "education_level", "level_order", "is_active")


class ClassConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = ClassGroup
        fields = ("academic_year", "grade", "name", "capacity", "is_active")


class DepartmentConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = Department
        fields = ("name", "code", "is_active")


class SubjectConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = Subject
        fields = ("code", "name")


class AssessmentCategoryConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = AssessmentCategory
        fields = ("name", "kind", "minimum_marks", "maximum_marks", "pass_marks", "is_active")

    def clean(self):
        cleaned = super().clean()
        minimum, passing, maximum = (
            cleaned.get("minimum_marks"),
            cleaned.get("pass_marks"),
            cleaned.get("maximum_marks"),
        )
        if minimum is not None and passing is not None and maximum is not None:
            if not minimum <= passing <= maximum:
                raise ValidationError("Marks must satisfy minimum ≤ pass mark ≤ maximum.")
        return cleaned


class GradeBoundaryConfigurationForm(TenantOwnedModelForm):
    class Meta:
        model = GradeBoundary
        fields = ("grade", "minimum_percent", "maximum_percent", "is_pass")

    def clean(self):
        cleaned = super().clean()
        minimum, maximum = cleaned.get("minimum_percent"), cleaned.get("maximum_percent")
        if minimum is not None and maximum is not None:
            overlaps = GradeBoundary.unscoped.filter(
                tenant=self.tenant,
                minimum_percent__lte=maximum,
                maximum_percent__gte=minimum,
            ).exclude(pk=self.instance.pk)
            if overlaps.exists():
                raise ValidationError("Grade boundaries may not overlap.")
        return cleaned


class AttendanceConfigurationForm(StyledFormMixin, forms.ModelForm):
    attendance_statuses = forms.CharField(
        label="Attendance statuses",
        help_text="One status per line in code | Display name format. Example: present | Present",
        widget=forms.Textarea(attrs={"rows": 5}),
    )

    class Meta:
        model = TenantConfiguration
        fields = ("attendance_statuses", "late_arrival_threshold_minutes", "attendance_reporting")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["attendance_statuses"] = "\n".join(
                f"{item['code']} | {item['label']}" for item in self.instance.attendance_statuses
            )

    def clean_attendance_statuses(self):
        lines = self.cleaned_data["attendance_statuses"].splitlines()
        result = []
        seen = set()
        for line in lines:
            if not line.strip():
                continue
            code, separator, label = line.partition("|")
            code, label = code.strip().lower(), label.strip()
            if not separator or not re.fullmatch(r"[a-z][a-z0-9_]{0,19}", code) or not label:
                raise ValidationError("Use one code | label pair per line with a valid code and label.")
            if code in seen:
                raise ValidationError("Attendance status codes must be unique.")
            seen.add(code)
            result.append({"code": code, "label": label})
        if not {"present", "absent"}.issubset(seen):
            raise ValidationError("Include both present and absent statuses.")
        return result


class NotificationConfigurationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TenantConfiguration
        fields = (
            "notify_by_email",
            "notify_in_system",
            "notify_announcements",
            "notify_attendance",
            "notify_academic_calendar",
        )


SECTION_CONFIG = {
    "academic-years": {
        "title": "Academic years",
        "model": AcademicYear,
        "form": AcademicYearConfigurationForm,
        "fields": ("name", "start_date", "end_date", "status", "is_current"),
        "active_field": None,
    },
    "terms": {
        "title": "Academic terms and semesters",
        "model": Term,
        "form": TermConfigurationForm,
        "fields": ("academic_year", "name", "start_date", "end_date"),
        "active_field": None,
    },
    "calendar": {
        "title": "Academic calendar and holidays",
        "model": SchoolCalendarEvent,
        "form": CalendarEventConfigurationForm,
        "fields": ("academic_year", "title", "kind", "start_date", "end_date", "notes"),
        "active_field": None,
    },
    "levels": {
        "title": "Education levels and forms",
        "model": Grade,
        "form": GradeConfigurationForm,
        "fields": ("name", "education_level", "level_order", "is_active"),
        "active_field": "is_active",
    },
    "classes": {
        "title": "Classes and streams",
        "model": ClassGroup,
        "form": ClassConfigurationForm,
        "fields": ("academic_year", "grade", "name", "capacity", "is_active"),
        "active_field": "is_active",
    },
    "departments": {
        "title": "Departments",
        "model": Department,
        "form": DepartmentConfigurationForm,
        "fields": ("name", "code", "is_active"),
        "active_field": "is_active",
    },
    "subjects": {
        "title": "Subjects",
        "model": Subject,
        "form": SubjectConfigurationForm,
        "fields": ("code", "name"),
        "active_field": None,
    },
    "assessment": {
        "title": "Assessment categories and examinations",
        "model": AssessmentCategory,
        "form": AssessmentCategoryConfigurationForm,
        "fields": ("name", "kind", "minimum_marks", "maximum_marks", "pass_marks", "is_active"),
        "active_field": "is_active",
    },
    "grading": {
        "title": "Grading scale",
        "model": GradeBoundary,
        "form": GradeBoundaryConfigurationForm,
        "fields": ("grade", "minimum_percent", "maximum_percent", "is_pass"),
        "active_field": None,
    },
}

