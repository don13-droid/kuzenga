from django import forms

from apps.core.context import get_current_tenant
from apps.core.forms import TenantModelForm
from apps.students.models import Student
from apps.tenancy.models import Membership

from .models import AcademicYear, ClassGroup, Grade, Subject, SubjectOffering, TeacherAllocation, Term
from .validation import TEACHING_ROLES

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class AcademicForm(TenantModelForm):
    expected_updated_at = forms.DateTimeField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance._state.adding:
            self.fields["expected_updated_at"].initial = self.instance.updated_at.isoformat()
            self.fields["expected_updated_at"].required = True
        for name in ("teacher", "class_teacher"):
            if name in self.fields:
                self.fields[name].queryset = Membership.objects.filter(
                    tenant=self.instance.tenant, role__in=TEACHING_ROLES, status="active", user__is_active=True,
                    user__is_superuser=False,
                ).select_related("user")


class AcademicYearForm(AcademicForm):
    class Meta:
        model = AcademicYear
        fields = ["name", "start_date", "end_date", "status", "is_current"]
        widgets = {"start_date": DATE, "end_date": DATE}

    def _get_validation_exclusions(self):
        # Current/active designation switches are performed atomically by the service.
        return super()._get_validation_exclusions() | {"status", "is_current"}


class TermForm(AcademicForm):
    class Meta:
        model = Term
        fields = ["academic_year", "name", "start_date", "end_date", "is_current"]
        widgets = {"start_date": DATE, "end_date": DATE}

    def _get_validation_exclusions(self):
        return super()._get_validation_exclusions() | {"is_current"}


class GradeForm(AcademicForm):
    class Meta:
        model = Grade
        fields = ["name", "level_order", "education_level", "is_active"]


class ClassGroupForm(AcademicForm):
    class Meta:
        model = ClassGroup
        fields = ["academic_year", "grade", "name", "code", "capacity", "class_teacher", "is_active"]


class SubjectForm(AcademicForm):
    class Meta:
        model = Subject
        fields = ["code", "name", "description", "is_active"]


class SubjectOfferingForm(AcademicForm):
    class Meta:
        model = SubjectOffering
        fields = ["academic_year", "subject", "grade", "class_group", "is_compulsory", "is_active"]


class TeacherAllocationForm(AcademicForm):
    class Meta:
        model = TeacherAllocation
        fields = ["offering", "class_group", "teacher", "term", "is_active"]


class ProgressionForm(forms.Form):
    students = forms.ModelMultipleChoiceField(queryset=Student.objects.none())
    target_class = forms.ModelChoiceField(queryset=ClassGroup.objects.none())
    effective_from = forms.DateField(widget=DATE)
    mode = forms.ChoiceField(choices=[("initial", "Initial placement"), ("promotion", "Promotion"),
                                     ("repetition", "Repetition"), ("transfer", "Class / stream transfer")])
    reason = forms.CharField(max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["students"].queryset = Student.objects.filter(status="active")
        self.fields["target_class"].queryset = ClassGroup.objects.filter(is_active=True).select_related("academic_year", "grade")

    def clean_students(self):
        students = list(self.cleaned_data["students"])
        if not 1 <= len(students) <= 100:
            raise forms.ValidationError("Select between 1 and 100 students.")
        return students


class ResourceFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=150, label="Search")
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.none(), required=False)
    active = forms.ChoiceField(choices=[("", "All states"), ("yes", "Active"), ("no", "Inactive")], required=False)
    teacher = forms.ModelChoiceField(queryset=Membership.objects.none(), required=False)

    def __init__(self, *args, kind, teacher_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["academic_year"].queryset = AcademicYear.objects.all()
        if kind not in ("classes", "terms", "offerings", "allocations"):
            self.fields.pop("academic_year")
        if kind not in ("classes", "grades", "subjects", "offerings", "allocations"):
            self.fields.pop("active")
        if kind != "allocations":
            self.fields.pop("teacher")
        else:
            teachers = Membership.objects.filter(tenant=get_current_tenant(), role__in=TEACHING_ROLES).select_related("user", "tenant")
            self.fields["teacher"].queryset = teachers.filter(user=teacher_user) if teacher_user else teachers
