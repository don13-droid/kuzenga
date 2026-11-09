from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TenantScopedModel

from .validation import TERMINAL_YEAR_STATUSES, class_peak, validate_related, validate_teacher


class AcademicYear(TenantScopedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_year_name_per_tenant"),
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")), name="year_end_after_start"
            ),
            models.UniqueConstraint(fields=["tenant"], condition=models.Q(is_current=True), name="uniq_current_year_tenant"),
            models.UniqueConstraint(fields=["tenant"], condition=models.Q(status="active"), name="uniq_active_year_tenant"),
        ]

    def clean(self):
        super().clean()
        if self.is_current and self.status in TERMINAL_YEAR_STATUSES:
            raise ValidationError({"is_current": "A completed, closed or archived year cannot be current."})
        if self.start_date and self.end_date:
            if AcademicYear.objects.filter(start_date__lte=self.end_date, end_date__gte=self.start_date).exclude(pk=self.pk).exists():
                raise ValidationError("Academic years may not overlap.")
            if not self._state.adding:
                if self.terms.filter(models.Q(start_date__lt=self.start_date) | models.Q(end_date__gt=self.end_date)).exists():
                    raise ValidationError("The new dates would exclude an existing term.")
                if self.calendar_events.filter(models.Q(start_date__lt=self.start_date) | models.Q(end_date__gt=self.end_date)).exists():
                    raise ValidationError("The new dates would exclude a calendar event.")

    def __str__(self):
        return self.name


class Term(TenantScopedModel):
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="terms")
    name = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False, db_default=False)

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "academic_year", "name"], name="uniq_term_per_year"
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")), name="term_end_after_start"
            ),
            models.UniqueConstraint(fields=["tenant"], condition=models.Q(is_current=True), name="uniq_current_term_tenant"),
        ]

    def clean(self):
        super().clean()
        validate_related(self, "academic_year")
        if self.academic_year_id and self.start_date and self.end_date and (
            self.start_date < self.academic_year.start_date
            or self.end_date > self.academic_year.end_date
        ):
            raise ValidationError("Term dates must fall within the selected academic year.")
        if self.academic_year_id and self.start_date and self.end_date and Term.objects.filter(
            academic_year_id=self.academic_year_id, start_date__lte=self.end_date, end_date__gte=self.start_date,
        ).exclude(pk=self.pk).exists():
            raise ValidationError("Terms in the same academic year may not overlap.")
        if self.is_current and self.academic_year_id and (
            not self.academic_year.is_current or self.academic_year.status in TERMINAL_YEAR_STATUSES
        ):
            raise ValidationError({"is_current": "A current term must belong to the current available year."})
        if not self._state.adding:
            original = Term.objects.filter(pk=self.pk).first()
            if original and original.academic_year_id != self.academic_year_id and TeacherAllocation.objects.filter(term=self).exists():
                raise ValidationError("A term with teacher allocations cannot move to another year.")

    def __str__(self):
        return f"{self.academic_year} - {self.name}"


class Grade(TenantScopedModel):
    """School-specific level name (Grade 1, Form 4, ...). Not a fixed hierarchy."""

    name = models.CharField(max_length=50)
    level_order = models.PositiveSmallIntegerField(default=0)
    education_level = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["level_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_grade_name_per_tenant")
        ]

    def __str__(self):
        return self.name


class ClassGroup(TenantScopedModel):
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="classes"
    )
    grade = models.ForeignKey(Grade, on_delete=models.PROTECT, related_name="classes")
    name = models.CharField(max_length=50, help_text="e.g. 4A, Blue, Stream 1")
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    code = models.CharField(max_length=30, blank=True, db_default="")
    class_teacher = models.ForeignKey("tenancy.Membership", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="class_groups")

    class Meta:
        ordering = ["grade__level_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "academic_year", "grade", "name"],
                name="uniq_class_per_year_grade",
            ),
            models.UniqueConstraint(fields=["tenant", "academic_year", "code"], condition=~models.Q(code=""),
                                    name="uniq_class_code_year"),
        ]

    def clean(self):
        super().clean()
        validate_related(self, "academic_year", "grade", "class_teacher")
        validate_teacher(self.class_teacher, self.tenant_id)
        if not self._state.adding:
            original = ClassGroup.objects.filter(pk=self.pk).first()
            if original and (original.academic_year_id != self.academic_year_id or original.grade_id != self.grade_id):
                if self.enrolments.exists() or self.subject_offerings.exists() or self.teacher_allocations.exists():
                    raise ValidationError("A class with placements or curriculum records cannot change its year or grade.")
            if self.capacity is not None and class_peak(self) > self.capacity:
                raise ValidationError({"capacity": "Capacity cannot be below recorded student occupancy."})

    def __str__(self):
        return f"{self.grade} {self.name} ({self.academic_year})"


class Subject(TenantScopedModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, db_default="")
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_subject_code_per_tenant")
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Department(TenantScopedModel):
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=30)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_department_code_per_tenant")
        ]

    def __str__(self):
        return self.name


class SubjectOffering(TenantScopedModel):
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="offerings")
    grade = models.ForeignKey(Grade, on_delete=models.PROTECT)
    class_group = models.ForeignKey(ClassGroup, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="subject_offerings")
    is_compulsory = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["subject__name", "grade__level_order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "academic_year", "grade", "subject"],
                condition=models.Q(class_group__isnull=True, is_active=True), name="uniq_grade_subject_offering"),
            models.UniqueConstraint(fields=["tenant", "academic_year", "class_group", "subject"],
                condition=models.Q(class_group__isnull=False, is_active=True), name="uniq_class_subject_offering"),
        ]

    def clean(self):
        super().clean()
        validate_related(self, "academic_year", "subject", "grade", "class_group")
        if self.class_group_id and (self.class_group.grade_id != self.grade_id or self.class_group.academic_year_id != self.academic_year_id):
            raise ValidationError("Offering class, grade and academic year must match.")
        if self.is_active and self.subject_id and self.grade_id and self.academic_year_id:
            if not self.subject.is_active or not self.grade.is_active or self.academic_year.status in TERMINAL_YEAR_STATUSES:
                raise ValidationError("Active offerings need an available subject, grade and year.")
            if self.class_group_id and not self.class_group.is_active:
                raise ValidationError("Choose an active class for an active offering.")
            peers = SubjectOffering.objects.filter(academic_year_id=self.academic_year_id, subject_id=self.subject_id,
                                                    grade_id=self.grade_id, is_active=True).exclude(pk=self.pk)
            if self.class_group_id:
                peers = peers.filter(models.Q(class_group__isnull=True) | models.Q(class_group_id=self.class_group_id))
            if peers.exists():
                raise ValidationError("This subject is already offered for the selected grade or class.")

    def __str__(self):
        return f"{self.subject} · {self.class_group or self.grade} · {self.academic_year}"


class TeacherAllocation(TenantScopedModel):
    offering = models.ForeignKey(SubjectOffering, on_delete=models.PROTECT, related_name="allocations")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.PROTECT, related_name="teacher_allocations")
    teacher = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="subject_allocations")
    term = models.ForeignKey(Term, null=True, blank=True, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["class_group__name", "offering__subject__name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "offering", "class_group", "teacher"],
                condition=models.Q(term__isnull=True, is_active=True), name="uniq_year_teacher_allocation"),
            models.UniqueConstraint(fields=["tenant", "offering", "class_group", "teacher", "term"],
                condition=models.Q(term__isnull=False, is_active=True), name="uniq_term_teacher_allocation"),
        ]

    def clean(self):
        super().clean()
        validate_related(self, "offering", "class_group", "teacher", "term")
        if not self.offering_id or not self.class_group_id or not self.teacher_id:
            return
        if self.is_active:
            validate_teacher(self.teacher, self.tenant_id)
            if not self.offering.is_active or not self.class_group.is_active:
                raise ValidationError("Choose an active offering and class.")
            if self.offering.academic_year.status in TERMINAL_YEAR_STATUSES:
                raise ValidationError("New active allocations require an available academic year.")
        if (self.offering.academic_year_id != self.class_group.academic_year_id
                or self.offering.grade_id != self.class_group.grade_id
                or (self.offering.class_group_id and self.offering.class_group_id != self.class_group_id)):
            raise ValidationError("The offering does not apply to this class.")
        if self.term_id and self.term.academic_year_id != self.offering.academic_year_id:
            raise ValidationError("The allocation term must belong to the offering's year.")
        if self.is_active:
            peers = TeacherAllocation.objects.filter(offering_id=self.offering_id, class_group_id=self.class_group_id,
                                                      teacher_id=self.teacher_id, is_active=True).exclude(pk=self.pk)
            if self.term_id:
                peers = peers.filter(models.Q(term__isnull=True) | models.Q(term_id=self.term_id))
            if peers.exists():
                raise ValidationError("This teacher already has an overlapping allocation for this offering and class.")


class SchoolCalendarEvent(TenantScopedModel):
    class Kind(models.TextChoices):
        OPENING = "opening", "Opening date"
        CLOSING = "closing", "Closing date"
        HOLIDAY = "holiday", "School holiday"
        EVENT = "event", "Calendar event"

    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="calendar_events"
    )
    title = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.EVENT)
    start_date = models.DateField()
    end_date = models.DateField()
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["start_date", "title"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="calendar_event_end_on_or_after_start",
            )
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.academic_year_id and self.start_date and self.end_date and (
            self.start_date < self.academic_year.start_date
            or self.end_date > self.academic_year.end_date
        ):
            raise ValidationError("Calendar dates must fall within the selected academic year.")


class AssessmentCategory(TenantScopedModel):
    class Kind(models.TextChoices):
        CONTINUOUS = "continuous", "Continuous assessment"
        EXAMINATION = "examination", "Examination"
        OTHER = "other", "Other assessment"

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    minimum_marks = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    maximum_marks = models.DecimalField(max_digits=7, decimal_places=2)
    pass_marks = models.DecimalField(max_digits=7, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_assessment_name_per_tenant"),
            models.CheckConstraint(
                condition=models.Q(minimum_marks__lte=models.F("pass_marks")),
                name="assessment_min_before_pass",
            ),
            models.CheckConstraint(
                condition=models.Q(pass_marks__lte=models.F("maximum_marks")),
                name="assessment_pass_before_max",
            ),
        ]


class GradeBoundary(TenantScopedModel):
    grade = models.CharField(max_length=20)
    minimum_percent = models.DecimalField(max_digits=5, decimal_places=2)
    maximum_percent = models.DecimalField(max_digits=5, decimal_places=2)
    is_pass = models.BooleanField(default=True)

    class Meta:
        ordering = ["-minimum_percent"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "grade"], name="uniq_grade_boundary_per_tenant"),
            models.CheckConstraint(
                condition=models.Q(minimum_percent__gte=0, maximum_percent__lte=100),
                name="grade_boundary_within_percentage",
            ),
            models.CheckConstraint(
                condition=models.Q(maximum_percent__gte=models.F("minimum_percent")),
                name="grade_boundary_max_after_min",
            ),
        ]

    def __str__(self):
        return self.grade
