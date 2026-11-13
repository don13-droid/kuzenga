from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.context import get_current_tenant
from apps.core.exceptions import TenantContextMissing, TenantMismatch
from apps.tenancy.models import Membership, Tenant
from apps.tenancy.permissions import has_permission

from .models import AdmissionSequence, Guardian, Student, StudentDocument, StudentEnrolment, StudentGuardian


def _write_context(actor=None, *records):
    tenant = get_current_tenant()
    if tenant is None:
        raise TenantContextMissing("Student operations require an active tenant.")
    if any(record is not None and record.tenant_id != tenant.pk for record in records):
        raise TenantMismatch("A related record belongs to another tenant.")
    # actor=None is reserved for trusted internal callers already using tenant_context.
    if actor is not None:
        member = Membership.objects.filter(user=actor, tenant=tenant, status="active").first()
        if not actor.is_active or not has_permission(member, "students.manage"):
            raise PermissionDenied
    return tenant


@transaction.atomic
def next_admission_number() -> str:
    """Unique per tenant. Uses a row lock so concurrent requests cannot reuse a number."""
    tenant = _write_context()
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    year = timezone.localdate().year % 100
    seq, _ = AdmissionSequence.objects.select_for_update().get_or_create(year=year)
    seq.last_number += 1
    while Student.objects.filter(admission_number=f"{year:02d}{seq.last_number:04d}").exists():
        seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    return f"{year:02d}{seq.last_number:04d}"


@transaction.atomic
def enrol_student(student, class_group, *, effective_from=None, actor=None, request=None) -> StudentEnrolment:
    from apps.academics.models import ClassGroup
    from apps.academics.validation import validate_placement

    tenant = _write_context(actor, student, class_group)
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    student = Student.objects.select_for_update().get(pk=student.pk)
    class_group = ClassGroup.objects.select_for_update().select_related("academic_year", "grade").get(pk=class_group.pk)
    if student.status != Student.Status.ACTIVE:
        raise ValidationError("Reactivate the student before assigning a class.")
    if not class_group.is_active:
        raise ValidationError("Choose an active class.")
    effective_from = effective_from or max(timezone.localdate(), class_group.academic_year.start_date)
    latest = StudentEnrolment.objects.filter(student=student).order_by("-effective_from", "-created_at").first()
    if latest and latest.effective_to is None and latest.class_group_id == class_group.pk:
        return latest
    validate_placement(student, class_group, effective_from)
    if latest and effective_from <= (latest.effective_to or latest.effective_from):
        raise ValidationError("The new class must start after the previous enrolment dates.")
    for open_enrolment in StudentEnrolment.objects.filter(
        student=student, effective_to__isnull=True
    ):
        if open_enrolment.effective_from > open_enrolment.class_group.academic_year.end_date:
            raise ValidationError("Resolve the previous enrolment's invalid dates before moving this student.")
        open_enrolment.effective_to = min(effective_from - timedelta(days=1), open_enrolment.class_group.academic_year.end_date)
        open_enrolment.save(update_fields=["effective_to", "updated_at"])
    enrolment = StudentEnrolment.objects.create(
        student=student, class_group=class_group, effective_from=effective_from
    )
    from apps.finance.student_accounts import account_for_enrolment
    account_for_enrolment(enrolment, actor)
    audit.record(
        "student.enrolled",
        actor=actor,
        obj=enrolment,
        request=request,
        student=student.pk,
        class_group=class_group.pk,
    )
    return enrolment


@transaction.atomic
def create_student(
    *,
    first_name,
    last_name,
    preferred_name="",
    date_of_birth=None,
    gender="",
    admission_number="",
    profile_image=None,
    guardian_data=None,
    class_group=None,
    actor=None,
    request=None,
) -> Student:
    tenant = _write_context(actor, class_group)
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    student = Student(
        tenant=tenant,
        admission_number=admission_number.strip() or next_admission_number(),
        first_name=first_name,
        last_name=last_name,
        preferred_name=preferred_name,
        date_of_birth=date_of_birth,
        gender=gender,
        profile_image=profile_image or "",
    )
    student.full_clean()
    student.save()
    audit.record("student.created", actor=actor, obj=student, request=request)
    if class_group is not None:
        enrol_student(student, class_group, actor=actor, request=request)
    if guardian_data:
        add_guardian(student, actor=actor, request=request, **guardian_data)
    return student


@transaction.atomic
def add_guardian(
    student,
    *,
    first_name="",
    last_name="",
    guardian=None,
    phone="",
    email="",
    relationship="",
    is_primary=False,
    can_collect=False,
    is_emergency=False,
    actor=None,
    request=None,
) -> StudentGuardian:
    tenant = _write_context(actor, student, guardian)
    student = Student.objects.select_for_update().get(pk=student.pk)
    if guardian is None:
        guardian = Guardian(tenant=tenant, first_name=first_name, last_name=last_name, phone=phone, email=email)
        guardian.full_clean()
        guardian.save()
    if (is_primary or is_emergency) and not (guardian.phone or guardian.email):
        raise ValidationError("Primary and emergency contacts need a phone number or email.")
    if is_primary:
        StudentGuardian.objects.filter(student=student, is_primary=True).update(is_primary=False)
    link, _ = StudentGuardian.objects.update_or_create(
        student=student, guardian=guardian,
        defaults={"relationship": relationship, "is_primary": is_primary,
                  "can_collect": can_collect, "is_emergency": is_emergency},
    )
    audit.record("guardian.linked", actor=actor, obj=link, request=request, student=student.pk)
    return link


@transaction.atomic
def update_student(student, *, actor, request=None, **data):
    _write_context(actor, student)
    student = Student.objects.select_for_update().get(pk=student.pk)
    changed = []
    for field in ("first_name", "last_name", "preferred_name", "date_of_birth", "gender", "profile_image"):
        if field in data and getattr(student, field) != data[field]:
            value = "" if field == "profile_image" and data[field] is False else data[field]
            setattr(student, field, value)
            changed.append(field)
    student.full_clean()
    student.save()
    if changed:
        audit.record("student.updated", actor=actor, obj=student, request=request,
                     changes={field: "[REDACTED]" for field in changed})
    return student


@transaction.atomic
def change_student_status(student, *, status, reason, actor, request=None):
    from apps.academics.validation import TERMINAL_YEAR_STATUSES, validate_placement

    tenant = _write_context(actor, student)
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    if status not in Student.Status.values or not reason.strip():
        raise ValidationError("Choose a valid status and enter a reason.")
    student = Student.objects.select_for_update().get(pk=student.pk)
    previous = student.status
    if status == previous:
        return student
    today = timezone.localdate()
    if status == Student.Status.ACTIVE:
        for enrolment in StudentEnrolment.objects.filter(student=student, effective_to__isnull=True).select_related("class_group__academic_year", "class_group__grade"):
            year = enrolment.class_group.academic_year
            if year.end_date >= today and year.status not in TERMINAL_YEAR_STATUSES:
                validate_placement(student, enrolment.class_group, max(today, year.start_date, enrolment.effective_from))
    if status in (Student.Status.TRANSFERRED, Student.Status.WITHDRAWN, Student.Status.GRADUATED, Student.Status.ARCHIVED):
        open_records = StudentEnrolment.objects.filter(student=student, effective_to__isnull=True)
        if open_records.filter(effective_from__gt=today).exists():
            raise ValidationError("A future enrolment exists. Resolve its dates before closing this student record.")
        open_records.update(effective_to=today, updated_at=timezone.now())
    student.status = status
    student.full_clean()
    student.save(update_fields=["status", "updated_at"])
    audit.record("student.status_changed", actor=actor, obj=student, request=request,
                 changes={"status": {"before": previous, "after": status}}, reason=reason)
    return student


@transaction.atomic
def upload_document(student, *, title, file, actor, request=None):
    tenant = _write_context(actor, student)
    document = StudentDocument(tenant=tenant, student=student, title=title, file=file, uploaded_by=actor)
    document.full_clean()
    audit.record("student.document_uploaded", actor=actor, obj=document, request=request, student=student.pk)
    document.save()
    return document
