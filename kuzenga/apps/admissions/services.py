"""School admissions workflows. Student and guardian writes stay in student services."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.validation import TERMINAL_YEAR_STATUSES
from apps.core import audit
from apps.core.context import get_current_tenant
from apps.core.models import AuditEvent
from apps.students import services as student_services
from apps.students.models import Student
from apps.tenancy.models import Membership, Tenant
from apps.tenancy.permissions import has_permission
from apps.tenancy.services import has_module

from .models import ApplicationDocument, ApplicationNote, StudentApplication

Status = StudentApplication.Status
TRANSITIONS = {
    Status.DRAFT: (Status.SUBMITTED,),
    Status.SUBMITTED: (Status.UNDER_REVIEW,),
    Status.UNDER_REVIEW: (Status.ACCEPTED, Status.REJECTED, Status.WAITLISTED),
    Status.WAITLISTED: (Status.UNDER_REVIEW, Status.ACCEPTED),
    Status.ACCEPTED: (),  # Only enrol_application can link a student and mark enrolled.
    Status.REJECTED: (),
    Status.ENROLLED: (),
}
EDITABLE_STATUSES = (Status.DRAFT, Status.SUBMITTED, Status.UNDER_REVIEW, Status.WAITLISTED)
APPLICATION_FIELDS = (
    "first_name", "last_name", "preferred_name", "date_of_birth", "gender", "intended_year",
    "intended_grade", "intended_class", "previous_school", "application_date", "guardian",
    "guardian_first_name", "guardian_last_name", "guardian_phone", "guardian_email", "guardian_relationship",
)


def authorize(actor, permission, *records):
    tenant = get_current_tenant()
    if (not actor or not actor.is_authenticated or not actor.is_active or actor.is_superuser
            or tenant is None or tenant.status not in (Tenant.Status.ACTIVE, Tenant.Status.TRIAL)):
        raise PermissionDenied
    member = Membership.objects.filter(user=actor, tenant=tenant, status=Membership.Status.ACTIVE).first()
    if not has_permission(member, permission) or not has_module(tenant, "students"):
        raise PermissionDenied
    if any(record is not None and record.tenant_id != tenant.pk for record in records):
        raise ValidationError("A related record belongs to another school.")
    return tenant


def _lock(application, actor, permission):
    tenant = authorize(actor, permission, application)
    # Consistent tenant -> application -> student lock order also serializes conversion.
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    return StudentApplication.objects.select_for_update().get(pk=application.pk)


def _record(application, action, *, actor, request=None, changes=None, note=""):
    event = audit.record(action, actor=actor, obj=application, tenant=application.tenant,
                         request=request, changes=changes)
    if note.strip():
        if len(note.strip()) > 4000:
            raise ValidationError("Notes must be 4,000 characters or shorter.")
        ApplicationNote.objects.create(tenant=application.tenant, application=application,
                                       audit_event=event, body=note.strip())
    return event


def _set_fields(application, data, actor):
    for field in APPLICATION_FIELDS:
        if field in data:
            setattr(application, field, data[field])
    authorize(actor, "admissions.manage", application.intended_year, application.intended_grade,
              application.intended_class, application.guardian)
    if application.intended_class_id:
        application.intended_year = application.intended_year or application.intended_class.academic_year
        application.intended_grade = application.intended_grade or application.intended_class.grade
    if application.guardian_id:
        guardian = application.guardian
        for field in ("first_name", "last_name", "phone", "email"):
            setattr(application, f"guardian_{field}", getattr(guardian, field))
    application.full_clean()


def _ready(application):
    if not application.intended_year_id or not application.intended_grade_id:
        raise ValidationError("Choose an intended academic year and grade or class before submission.")
    if not application.guardian_first_name or not application.guardian_last_name:
        raise ValidationError("Provide a guardian's full name or select an existing guardian.")
    if not (application.guardian_phone or application.guardian_email):
        raise ValidationError("Provide a guardian phone number or email before submission.")
    if not application.intended_grade.is_active or application.intended_year.status in TERMINAL_YEAR_STATUSES:
        raise ValidationError("Choose an available grade and academic year.")
    if application.intended_class_id and not application.intended_class.is_active:
        raise ValidationError("The intended class is no longer active.")


@transaction.atomic
def create_application(*, actor, data, submit=False, document_data=None, request=None):
    tenant = authorize(actor, "admissions.manage")
    application = StudentApplication(tenant=tenant)
    _set_fields(application, data, actor)
    if submit:
        _ready(application)
    application.save()
    _record(application, "admissions.created", actor=actor, request=request)
    if submit:
        application = transition_application(application, target=Status.SUBMITTED, actor=actor, request=request)
    if document_data:
        upload_document(application, actor=actor, request=request, **document_data)
        application.refresh_from_db()
    return application


@transaction.atomic
def update_application(application, *, actor, data, expected_updated_at, reason="", request=None):
    application = _lock(application, actor, "admissions.manage")
    if application.updated_at != expected_updated_at:
        raise ValidationError("This application changed. Reload it before editing.")
    if application.status not in EDITABLE_STATUSES:
        raise ValidationError("Accepted, rejected and enrolled applications are read-only.")
    if application.status != Status.DRAFT and not reason.strip():
        raise ValidationError("Enter a reason for changing a submitted application.")
    before = {field: getattr(application, field) for field in APPLICATION_FIELDS}
    _set_fields(application, data, actor)
    if application.status != Status.DRAFT:
        _ready(application)
    changed = [field for field in APPLICATION_FIELDS if before[field] != getattr(application, field)]
    if changed:
        application.save()
        _record(application, "admissions.updated", actor=actor, request=request,
                changes={field: "[REDACTED]" for field in changed}, note=reason)
    return application


@transaction.atomic
def transition_application(application, *, target, actor, reason="", request=None):
    permission = "admissions.manage" if target == Status.SUBMITTED else "admissions.review"
    current = _lock(application, actor, permission)
    if current.updated_at != application.updated_at or current.status != application.status:
        raise ValidationError("This application changed. Reload it before making a decision.")
    if target not in TRANSITIONS.get(current.status, ()):
        raise ValidationError("This status transition is not allowed.")
    if target in (Status.ACCEPTED, Status.REJECTED, Status.WAITLISTED) or current.status == Status.WAITLISTED:
        if not reason.strip():
            raise ValidationError("Enter a reason for this decision.")
    _ready(current)
    previous = current.status
    current.status = target
    current.full_clean()
    current.save(update_fields=["status", "updated_at"])
    _record(current, f"admissions.{target}", actor=actor, request=request,
            changes={"status": {"before": previous, "after": target}}, note=reason)
    return current


@transaction.atomic
def add_review_note(application, *, actor, body, request=None):
    application = _lock(application, actor, "admissions.review")
    if not body.strip():
        raise ValidationError("Enter a review note.")
    application.save(update_fields=["updated_at"])
    return _record(application, "admissions.review_note_added", actor=actor, request=request, note=body)


@transaction.atomic
def upload_document(application, *, actor, kind, title, file, request=None):
    application = _lock(application, actor, "admissions.manage")
    if application.status not in EDITABLE_STATUSES:
        raise ValidationError("Documents cannot be changed after the application decision.")
    document = ApplicationDocument(tenant=application.tenant, application=application,
                                   kind=kind, title=title, file=file)
    document.full_clean()
    application.save(update_fields=["updated_at"])
    _record(application, "admissions.document_uploaded", actor=actor, request=request,
            changes={"document": {"before": None, "after": str(document.pk)}})
    document.save()
    return document


@transaction.atomic
def enrol_application(application, *, actor, class_group, effective_from=None, admission_number="", request=None):
    application = _lock(application, actor, "admissions.enrol")
    authorize(actor, "students.manage")
    if application.status == Status.ENROLLED and application.student_id:
        return Student.objects.get(pk=application.student_id)
    if application.status != Status.ACCEPTED:
        raise ValidationError("Only accepted applications can be enrolled.")
    if class_group is None:
        raise ValidationError("Choose a class for enrolment.")
    authorize(actor, "admissions.enrol", class_group)
    _ready(application)
    if (class_group.academic_year_id != application.intended_year_id
            or class_group.grade_id != application.intended_grade_id
            or (application.intended_class_id and class_group.pk != application.intended_class_id)):
        raise ValidationError("The class must match the accepted academic year, grade and intended class.")
    effective_from = effective_from or max(timezone.localdate(), application.intended_year.start_date)
    if not application.intended_year.start_date <= effective_from <= application.intended_year.end_date:
        raise ValidationError("The enrolment date must fall within the intended academic year.")
    if application.date_of_birth and Student.objects.filter(
        first_name__iexact=application.first_name, last_name__iexact=application.last_name,
        date_of_birth=application.date_of_birth,
    ).exists():
        raise ValidationError("A student with this name and birth date already exists. Resolve that record before enrolment.")
    guardian_data = {"relationship": application.guardian_relationship, "is_primary": True}
    if application.guardian_id:
        guardian_data["guardian"] = application.guardian
    else:
        guardian_data.update(first_name=application.guardian_first_name, last_name=application.guardian_last_name,
                             phone=application.guardian_phone, email=application.guardian_email)
    student = student_services.create_student(
        actor=actor, request=request, first_name=application.first_name, last_name=application.last_name,
        preferred_name=application.preferred_name, date_of_birth=application.date_of_birth,
        gender=application.gender, admission_number=admission_number, guardian_data=guardian_data,
    )
    student_services.enrol_student(student, class_group, actor=actor, request=request, effective_from=effective_from)
    for document in ApplicationDocument.objects.filter(application=application):
        try:
            with document.file.open("rb"):
                student_services.upload_document(student, actor=actor, request=request,
                                                  title=document.title, file=document.file)
        except OSError as exc:
            raise ValidationError("A supporting document is unavailable. Restore it before enrolment.") from exc
    application.student = student
    application.status = Status.ENROLLED
    application.full_clean()
    application.save(update_fields=["student", "status", "updated_at"])
    _record(application, "admissions.enrolled", actor=actor, request=request,
            changes={"status": {"before": Status.ACCEPTED, "after": Status.ENROLLED}})
    return student


def application_history(application, *, actor):
    authorize(actor, "admissions.view", application)
    return AuditEvent.objects.filter(tenant_id=application.tenant_id, object_type="StudentApplication",
                                     object_id=str(application.pk)).select_related("actor", "admission_note").order_by("-created_at", "-pk")
