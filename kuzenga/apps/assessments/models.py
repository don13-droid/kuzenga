from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TenantManager, TenantScopedModel


class ValidatedModel(TenantScopedModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from apps.core.context import get_current_tenant

        if not self.tenant_id:
            self.tenant = get_current_tenant()
        self._check_related_tenants()
        self.full_clean()
        return super().save(*args, **kwargs)


class ResultPolicy(ValidatedModel):
    name = models.CharField(max_length=100, unique=False)
    continuous_weight = models.DecimalField(max_digits=5, decimal_places=2, default=40)
    examination_weight = models.DecimalField(max_digits=5, decimal_places=2, default=60)
    missing = models.CharField(
        max_length=10,
        choices=[("block", "Require all marks"), ("zero", "Missing marks count as zero")],
        default="block",
    )
    rankings = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="assessment_policy_name")]

    def clean(self):
        if (
            self.continuous_weight < 0
            or self.examination_weight < 0
            or self.continuous_weight + self.examination_weight != Decimal("100")
        ):
            raise ValidationError("Continuous and examination weights must be nonnegative and total 100.")

    def __str__(self):
        return self.name


class Assessment(ValidatedModel):
    title = models.CharField(max_length=160)
    kind = models.CharField(
        max_length=20,
        choices=[
            (x, x.replace("_", " ").title())
            for x in ["assignment", "test", "quiz", "practical", "project", "continuous", "examination"]
        ],
    )
    category = models.ForeignKey("academics.AssessmentCategory", on_delete=models.PROTECT)
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT)
    class_group = models.ForeignKey("academics.ClassGroup", on_delete=models.PROTECT)
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT)
    policy = models.ForeignKey(ResultPolicy, on_delete=models.PROTECT)
    date = models.DateField()
    maximum_marks = models.DecimalField(max_digits=7, decimal_places=2)
    weight = models.DecimalField(max_digits=7, decimal_places=2, default=1)
    status = models.CharField(
        max_length=12,
        choices=[
            (s, s.replace("_", " ").title()) for s in ["draft", "submitted", "under_review", "approved", "published"]
        ],
        default="draft",
        editable=False,
    )
    feedback = models.TextField(blank=True, editable=False)

    class Meta:
        ordering = ["-date", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "term", "class_group", "subject", "title"], name="assessment_unique_title"
            ),
            models.CheckConstraint(
                condition=models.Q(maximum_marks__gt=0, weight__gt=0), name="assessment_positive_values"
            ),
        ]

    def clean(self):
        if self.term_id and self.class_group_id:
            if self.term.academic_year_id != self.class_group.academic_year_id:
                raise ValidationError("Class and term must belong to the same academic year.")
            if self.date and not self.term.start_date <= self.date <= self.term.end_date:
                raise ValidationError("Assessment date must fall within the term.")
        if self.category_id and self.maximum_marks and self.maximum_marks > self.category.maximum_marks:
            raise ValidationError("Maximum marks exceed the configured category limit.")

    def __str__(self):
        return self.title


class Mark(ValidatedModel):
    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="marks")
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="assessment_marks")
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    exempt = models.BooleanField(default=False)
    comment = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "assessment", "student"], name="assessment_unique_mark"),
            models.CheckConstraint(
                condition=models.Q(score__isnull=True) | models.Q(score__gte=0, exempt=False),
                name="assessment_valid_mark",
            ),
        ]

    def clean(self):
        if self.exempt and self.score is not None:
            raise ValidationError("An exempt mark cannot have a score.")
        if self.score is not None and (self.score < 0 or self.score > self.assessment.maximum_marks):
            raise ValidationError("Score must be between zero and the assessment maximum.")


class Examination(ValidatedModel):
    assessment = models.OneToOneField(Assessment, on_delete=models.PROTECT, related_name="examination")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    room = models.CharField(max_length=100)
    invigilator = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT)

    def clean(self):
        from apps.tenancy.models import Role

        if not self.starts_at or not self.ends_at or not self.assessment_id or not self.invigilator_id:
            return
        if self.invigilator.tenant_id != self.tenant_id:
            raise ValidationError("Invigilator belongs to another school.")
        if self.ends_at <= self.starts_at:
            raise ValidationError("Examination end must follow its start.")
        if self.assessment.kind != "examination":
            raise ValidationError("Only examinations may be scheduled.")
        if self.starts_at.date() != self.assessment.date:
            raise ValidationError("Schedule must match the assessment date.")
        if self.invigilator.status != "active" or self.invigilator.role in [Role.STUDENT, Role.GUARDIAN, Role.BURSAR]:
            raise ValidationError("Choose an active staff invigilator.")
        clashes = Examination.objects.filter(starts_at__lt=self.ends_at, ends_at__gt=self.starts_at).exclude(pk=self.pk)
        if clashes.filter(
            models.Q(room__iexact=self.room)
            | models.Q(invigilator=self.invigilator)
            | models.Q(assessment__class_group=self.assessment.class_group)
        ).exists():
            raise ValidationError("Room, class or invigilator clashes with another examination.")


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Published results are immutable.")

    def delete(self):
        raise ValidationError("Published results are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Published results are immutable.")


class PublishedResult(TenantScopedModel):
    objects = TenantManager.from_queryset(ImmutableQuerySet)()
    unscoped = ImmutableQuerySet.as_manager()
    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="published_results")
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="published_results")
    snapshot = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "assessment", "student"], name="assessment_unique_publication")
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Published results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Published results are immutable.")


class ReportComment(ValidatedModel):
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT)
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT)
    headmaster_comment = models.TextField(max_length=2000)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "student", "term"], name="assessment_report_comment")]
