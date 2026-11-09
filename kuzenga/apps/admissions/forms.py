from django import forms
from django.utils import timezone

from apps.academics.models import AcademicYear, ClassGroup, Grade
from apps.core.forms import TenantModelForm

from .models import ApplicationDocument, StudentApplication
from .services import APPLICATION_FIELDS, TRANSITIONS


class ApplicationForm(TenantModelForm):
    reason = forms.CharField(required=False, max_length=4000, widget=forms.Textarea(attrs={"rows": 2}),
                             help_text="Required when changing a submitted application. Stored as a private note.")
    expected_updated_at = forms.DateTimeField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = StudentApplication
        fields = APPLICATION_FIELDS
        widgets = {name: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
                   for name in ("date_of_birth", "application_date")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["application_date"].required = False
        self.fields["guardian"].help_text = "Choose an existing guardian or enter new contact details below."
        if self.instance._state.adding:
            self.fields.pop("reason")
            self.fields.pop("expected_updated_at")
        else:
            self.fields["expected_updated_at"].required = True
            self.fields["expected_updated_at"].initial = self.instance.updated_at.isoformat()
            if self.instance.guardian_id:
                for field in ("guardian_first_name", "guardian_last_name", "guardian_phone", "guardian_email"):
                    self.initial[field] = ""

    def clean(self):
        data = super().clean()
        data["application_date"] = data.get("application_date") or timezone.localdate()
        group = data.get("intended_class")
        if group:
            data["intended_year"] = data.get("intended_year") or group.academic_year
            data["intended_grade"] = data.get("intended_grade") or group.grade
        if data.get("guardian") and any(data.get(field) for field in
                ("guardian_first_name", "guardian_last_name", "guardian_phone", "guardian_email")):
            raise forms.ValidationError("Choose an existing guardian or enter new guardian details, not both.")
        return data


class TransitionForm(forms.Form):
    target = forms.ChoiceField(label="Next status")
    expected_updated_at = forms.DateTimeField(widget=forms.HiddenInput)
    reason = forms.CharField(required=False, max_length=4000, widget=forms.Textarea(attrs={"rows": 3}),
                             label="Decision reason / review note")

    def __init__(self, *args, application, can_submit=False, can_review=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].choices = [
            (status, StudentApplication.Status(status).label)
            for status in TRANSITIONS[application.status]
            if (status == "submitted" and can_submit) or (status != "submitted" and can_review)
        ]
        self.fields["expected_updated_at"].initial = application.updated_at.isoformat()


class ReviewNoteForm(forms.Form):
    body = forms.CharField(max_length=4000, widget=forms.Textarea(attrs={"rows": 3}), label="Private review note")


class ApplicationDocumentForm(TenantModelForm):
    class Meta:
        model = ApplicationDocument
        fields = ("kind", "title", "file")


class ApplicationFilterForm(forms.Form):
    q = forms.CharField(max_length=150, required=False, label="Applicant, reference or guardian")
    status = forms.ChoiceField(choices=[("", "All statuses"), *StudentApplication.Status.choices], required=False)
    grade = forms.ModelChoiceField(queryset=Grade.objects.all(), required=False)
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.all(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grade"].queryset = Grade.objects.all()
        self.fields["academic_year"].queryset = AcademicYear.objects.all()


class EnrolmentForm(forms.Form):
    class_group = forms.ModelChoiceField(queryset=ClassGroup.objects.all())
    effective_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}),
                                      help_text="Must fall within the intended academic year. Defaults to today or the year's start, whichever is later.")
    admission_number = forms.CharField(required=False, max_length=30, help_text="Leave blank to use the existing admission-number generator.")

    def __init__(self, *args, application, **kwargs):
        super().__init__(*args, **kwargs)
        groups = ClassGroup.objects.filter(academic_year_id=application.intended_year_id,
                                           grade_id=application.intended_grade_id, is_active=True)
        if application.intended_class_id:
            groups = groups.filter(pk=application.intended_class_id)
        self.fields["class_group"].queryset = groups.select_related("grade", "academic_year")
        self.fields["class_group"].initial = application.intended_class_id
