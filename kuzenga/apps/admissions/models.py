from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TenantManager, TenantScopedModel
from apps.students.models import Student
from apps.students.storage import StudentDocumentStorage
from apps.students.validators import validate_student_document


def application_reference():
    return f"ADM-{uuid4().hex[:12].upper()}"


def application_document_upload_to(instance, filename):
    return f"admission-documents/{instance.tenant_id}/{uuid4().hex}{Path(filename).suffix.lower()}"


class StudentApplication(TenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        WAITLISTED = "waitlisted", "Waitlisted"
        ENROLLED = "enrolled", "Enrolled"

    reference = models.CharField(max_length=20, default=application_reference, editable=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=Student.Gender.choices, blank=True)
    intended_year = models.ForeignKey("academics.AcademicYear", null=True, blank=True, on_delete=models.PROTECT)
    intended_grade = models.ForeignKey("academics.Grade", null=True, blank=True, on_delete=models.PROTECT)
    intended_class = models.ForeignKey("academics.ClassGroup", null=True, blank=True, on_delete=models.PROTECT)
    previous_school = models.CharField(max_length=200, blank=True)
    application_date = models.DateField(default=timezone.localdate)
    guardian = models.ForeignKey("students.Guardian", null=True, blank=True, on_delete=models.PROTECT)
    guardian_first_name = models.CharField(max_length=100, blank=True)
    guardian_last_name = models.CharField(max_length=100, blank=True)
    guardian_phone = models.CharField(max_length=30, blank=True)
    guardian_email = models.EmailField(blank=True)
    guardian_relationship = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    student = models.OneToOneField("students.Student", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="admission_application")

    class Meta:
        ordering = ["-application_date", "-created_at", "-pk"]
        indexes = [models.Index(fields=["tenant", "status", "-created_at"], name="admission_tenant_status_idx")]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reference"], name="uniq_application_reference"),
            models.CheckConstraint(condition=models.Q(status__in=["draft", "submitted", "under_review", "accepted", "rejected", "waitlisted", "enrolled"]), name="admission_valid_status"),
            models.CheckConstraint(
                condition=(models.Q(status="enrolled", student__isnull=False)
                           | (~models.Q(status="enrolled") & models.Q(student__isnull=True))),
                name="admission_student_status_match",
            ),
        ]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def clean(self):
        super().clean()
        errors = {}
        for field in ("intended_year", "intended_grade", "intended_class", "guardian", "student"):
            if getattr(self, f"{field}_id") and getattr(self, field).tenant_id != self.tenant_id:
                errors[field] = "Choose a record belonging to this school."
        if self.date_of_birth and self.date_of_birth > timezone.localdate():
            errors["date_of_birth"] = "Date of birth cannot be in the future."
        if self.application_date and self.application_date > timezone.localdate():
            errors["application_date"] = "Application date cannot be in the future."
        if self.intended_class_id:
            if self.intended_class.academic_year_id != self.intended_year_id:
                errors["intended_class"] = "The class must belong to the intended academic year."
            if self.intended_grade_id != self.intended_class.grade_id:
                errors["intended_grade"] = "The grade must match the intended class."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.reference


class ApplicationDocument(TenantScopedModel):
    class Kind(models.TextChoices):
        BIRTH_CERTIFICATE = "birth_certificate", "Birth certificate"
        SCHOOL_RECORD = "school_record", "Previous school record"
        TRANSFER_LETTER = "transfer_letter", "Transfer letter"
        OTHER = "other", "Other supporting document"

    application = models.ForeignKey(StudentApplication, on_delete=models.PROTECT, related_name="documents")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=120)
    file = models.FileField(storage=StudentDocumentStorage(), upload_to=application_document_upload_to,
                            validators=[validate_student_document])

    class Meta:
        ordering = ["-created_at", "-pk"]


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RuntimeError("Application notes are append-only.")

    def delete(self):
        raise RuntimeError("Application notes are append-only.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise RuntimeError("Application notes are append-only.")


class ApplicationNote(TenantScopedModel):
    application = models.ForeignKey(StudentApplication, on_delete=models.PROTECT, related_name="notes")
    audit_event = models.OneToOneField("core.AuditEvent", on_delete=models.PROTECT, related_name="admission_note")
    body = models.TextField(max_length=4000)

    objects = TenantManager.from_queryset(AppendOnlyQuerySet)()
    unscoped = models.Manager.from_queryset(AppendOnlyQuerySet)()

    class Meta:
        ordering = ["-created_at", "-pk"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Application notes are append-only.")
        if (self.audit_event.tenant_id != self.tenant_id
                or self.audit_event.object_type != "StudentApplication"
                or self.audit_event.object_id != str(self.application_id)):
            raise ValidationError("The note must refer to this application's audit event.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Application notes are append-only.")
