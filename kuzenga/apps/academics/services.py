from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.core import audit
from apps.core.context import get_current_tenant, tenant_context
from apps.tenancy.models import Membership, Tenant
from apps.tenancy.permissions import has_permission

from .models import AcademicYear, Subject, SubjectOffering, TeacherAllocation, Term
from .validation import TERMINAL_YEAR_STATUSES


def authorize(actor, permission="academics.manage", *records):
    from apps.tenancy.services import has_module

    tenant = get_current_tenant()
    if not actor or not actor.is_active or actor.is_superuser or tenant is None or tenant.status not in ("active", "trial"):
        raise PermissionDenied
    member = Membership.objects.filter(user=actor, tenant=tenant, status="active").first()
    if not has_permission(member, permission) or not has_module(tenant, "academics"):
        raise PermissionDenied
    if any(record is not None and record.tenant_id != tenant.pk for record in records):
        raise ValidationError("A related record belongs to another school.")
    return tenant


def _changes(before, instance):
    return {field: {"before": value, "after": getattr(instance, field)}
            for field, value in before.items() if value != getattr(instance, field)}


def _audit_period(record, actor, request, **values):
    before = {key: getattr(record, key) for key in values}
    for key, value in values.items():
        setattr(record, key, value)
    record.save(update_fields=[*values, "updated_at"])
    audit.record("academic.period_changed", actor=actor, obj=record, tenant=record.tenant,
                 request=request, changes=_changes(before, record))


@transaction.atomic
def save_record(instance, *, actor, request=None, expected_updated_at=None, platform=False):
    if platform:
        if not actor.is_active or not actor.is_superuser:
            raise PermissionDenied
        tenant = instance.tenant
    else:
        tenant = authorize(actor, "academics.manage", instance)
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    with tenant_context(tenant):
        model = type(instance)
        original = model.objects.select_for_update().filter(pk=instance.pk).first()
        if original and expected_updated_at and original.updated_at != expected_updated_at:
            raise ValidationError("This record changed. Reload it before editing.")
        before = {field.attname: getattr(original, field.attname) if original else None
                  for field in instance._meta.concrete_fields if field.name not in ("id", "tenant", "created_at", "updated_at")}
        if isinstance(instance, AcademicYear):
            others = AcademicYear.objects.exclude(pk=instance.pk)
            if instance.status == AcademicYear.Status.ACTIVE:
                for year in others.filter(status=AcademicYear.Status.ACTIVE):
                    for term in Term.objects.filter(academic_year=year, is_current=True):
                        _audit_period(term, actor, request, is_current=False)
                    _audit_period(year, actor, request, status=AcademicYear.Status.COMPLETED, is_current=False)
            if instance.is_current:
                for year in others.filter(is_current=True):
                    for term in Term.objects.filter(academic_year=year, is_current=True):
                        _audit_period(term, actor, request, is_current=False)
                    _audit_period(year, actor, request, is_current=False)
            elif original and original.is_current:
                if instance.status not in TERMINAL_YEAR_STATUSES:
                    raise ValidationError("Select a replacement current year before clearing this designation.")
                for term in Term.objects.filter(academic_year=instance, is_current=True):
                    _audit_period(term, actor, request, is_current=False)
        if isinstance(instance, Term) and instance.is_current:
            for term in Term.objects.filter(is_current=True).exclude(pk=instance.pk):
                _audit_period(term, actor, request, is_current=False)
        if isinstance(instance, (SubjectOffering, TeacherAllocation)) and original:
            # Preserve historical allocation identities; remove safely via active state.
            fields = ("academic_year_id", "subject_id", "grade_id", "class_group_id") if isinstance(instance, SubjectOffering) else ("offering_id", "class_group_id", "teacher_id", "term_id")
            if any(getattr(original, field) != getattr(instance, field) for field in fields):
                raise ValidationError("Deactivate this allocation/offering and create a replacement to preserve history.")
        if isinstance(instance, SubjectOffering) and not instance.is_active:
            for allocation in instance.allocations.filter(is_active=True):
                _audit_period(allocation, actor, request, is_active=False)
        if isinstance(instance, Subject) and not instance.is_active:
            for offering in instance.offerings.filter(is_active=True):
                offering.is_active = False
                save_record(offering, actor=actor, request=request, platform=platform)
        instance.full_clean()
        instance.save()
        changes = _changes(before, instance)
        if changes:
            audit.record("academic.record_updated" if original else "academic.record_created", actor=actor,
                         obj=instance, tenant=tenant, request=request, changes=changes)
        return instance


@transaction.atomic
def progress_students(*, students, target_class, effective_from, mode, reason, actor, request=None):
    from apps.students.models import Student, StudentEnrolment
    from apps.students.services import enrol_student

    tenant = authorize(actor, "academics.manage", target_class, *students)
    authorize(actor, "students.manage")
    if mode not in ("initial", "promotion", "repetition", "transfer") or not reason.strip():
        raise ValidationError("Choose a progression type and enter a reason.")
    if not 1 <= len(students) <= 100 or len({student.pk for student in students}) != len(students):
        raise ValidationError("Select between 1 and 100 distinct students.")
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    results = []
    for selected in sorted(students, key=lambda student: str(student.pk)):
        student = Student.objects.select_for_update().get(pk=selected.pk)
        latest = StudentEnrolment.objects.filter(student=student).select_related("class_group__grade", "class_group__academic_year").order_by("-effective_from", "-created_at").first()
        if latest and latest.effective_to is None and latest.class_group_id == target_class.pk:
            results.append(latest)
            continue
        if mode == "initial" and latest:
            raise ValidationError("Initial placement is only for a student without placement history.")
        if mode in ("promotion", "repetition"):
            if not latest or target_class.academic_year.start_date <= latest.class_group.academic_year.start_date:
                raise ValidationError("Promotion/repetition requires a placement in a later academic year.")
            if mode == "promotion" and target_class.grade.level_order <= latest.class_group.grade.level_order:
                raise ValidationError("Promotion requires a higher grade/form level.")
            if mode == "repetition" and target_class.grade_id != latest.class_group.grade_id:
                raise ValidationError("Repetition keeps the same grade/form level.")
        result = enrol_student(student, target_class, effective_from=effective_from, actor=actor, request=request)
        audit.record("academic.student_progressed", actor=actor, obj=student, tenant=tenant, request=request,
                     student=student.pk, mode=mode, reason=reason,
                     changes={"class": {"before": str(latest.class_group_id) if latest else None, "after": str(target_class.pk)}})
        results.append(result)
    return results
