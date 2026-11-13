from django import forms

from apps.academics.models import AssessmentCategory, GradeBoundary

from .models import Assessment, Examination, ReportComment, ResultPolicy


class AssessmentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = [
            "title",
            "kind",
            "category",
            "term",
            "class_group",
            "subject",
            "policy",
            "date",
            "maximum_marks",
            "weight",
        ]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class PolicyForm(forms.ModelForm):
    class Meta:
        model = ResultPolicy
        fields = ["name", "continuous_weight", "examination_weight", "missing", "rankings"]


class ExaminationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core.context import get_current_tenant

        self.fields["invigilator"].queryset = (
            self.fields["invigilator"]
            .queryset.filter(tenant=get_current_tenant(), status="active")
            .exclude(role__in=["student", "guardian", "bursar"])
        )

    class Meta:
        model = Examination
        fields = ["starts_at", "ends_at", "room", "invigilator"]
        widgets = {name: forms.DateTimeInput(attrs={"type": "datetime-local"}) for name in ["starts_at", "ends_at"]}


class MarkForm(forms.Form):
    student = forms.UUIDField(widget=forms.HiddenInput)
    score = forms.DecimalField(max_digits=7, decimal_places=2, required=False)
    exempt = forms.BooleanField(required=False)
    comment = forms.CharField(max_length=500, required=False)


class ReportCommentForm(forms.ModelForm):
    class Meta:
        model = ReportComment
        fields = ["headmaster_comment"]


class CategoryForm(forms.ModelForm):
    class Meta:
        model = AssessmentCategory
        fields = ["name", "kind", "minimum_marks", "maximum_marks", "pass_marks", "is_active"]


class BoundaryForm(forms.ModelForm):
    class Meta:
        model = GradeBoundary
        fields = ["grade", "minimum_percent", "maximum_percent", "is_pass"]

    def clean(self):
        data = super().clean()
        low, high = data.get("minimum_percent"), data.get("maximum_percent")
        if (
            low is not None
            and high is not None
            and GradeBoundary.objects.filter(minimum_percent__lte=high, maximum_percent__gte=low)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("Grade boundaries must not overlap.")
        return data
