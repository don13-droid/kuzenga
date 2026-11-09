from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.academics.models import ClassGroup
from apps.core.models import TenantScopedModel
from apps.core.validators import validate_uploaded_image

from .storage import StudentDocumentStorage
from .validators import validate_student_document


def student_image_upload_to(instance, filename):
    return f"student-images/{instance.tenant_id}/{uuid4().hex}{Path(filename).suffix.lower()}"


def student_document_upload_to(instance, filename):
    return f"student-documents/{instance.tenant_id}/{uuid4().hex}{Path(filename).suffix.lower()}"


class Student(TenantScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRANSFERRED = "transferred", "Transferred"
        WITHDRAWN = "withdrawn", "Withdrawn"
        GRADUATED = "graduated", "Graduated"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"

    class Gender(models.TextChoices):
        FEMALE = "F", "Female"
        MALE = "M", "Male"
        OTHER = "O", "Other / not stated"

    admission_number = models.CharField(max_length=30)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    profile_image = models.ImageField(
        upload_to=student_image_upload_to, blank=True, db_default="", validators=[validate_uploaded_image]
    )

    def clean(self):
        super().clean()
        if self.date_of_birth and self.date_of_birth > timezone.localdate():
            raise ValidationError({"date_of_birth": "Date of birth cannot be in the future."})

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "admission_number"], name="uniq_admission_no_per_tenant"
            )
        ]
        indexes = [models.Index(fields=["tenant", "last_name"])]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.full_name} ({self.admission_number})"


class AdmissionSequence(TenantScopedModel):
    """Per-tenant, per-year counter for admission numbers."""

    year = models.PositiveSmallIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "year"], name="uniq_admission_seq_year")
        ]


class Guardian(TenantScopedModel):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class StudentGuardian(TenantScopedModel):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="guardian_links")
    guardian = models.ForeignKey(Guardian, on_delete=models.PROTECT, related_name="student_links")
    relationship = models.CharField(max_length=50, blank=True)
    is_primary = models.BooleanField(default=False)
    can_collect = models.BooleanField(default=False)
    is_emergency = models.BooleanField(default=False, db_default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "student", "guardian"], name="uniq_student_guardian"
            )
        ]


class StudentEnrolment(TenantScopedModel):
    """Class membership with effective dates. History is never overwritten."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="enrolments")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.PROTECT, related_name="enrolments")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-effective_from"]
        indexes = [models.Index(fields=["tenant", "class_group", "effective_from"])]

    def clean(self):
        super().clean()
        if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "The end cannot precede the start."})


class StudentDocument(TenantScopedModel):
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="documents")
    title = models.CharField(max_length=120)
    file = models.FileField(
        upload_to=student_document_upload_to, storage=StudentDocumentStorage(),
        validators=[validate_student_document],
    )
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title
