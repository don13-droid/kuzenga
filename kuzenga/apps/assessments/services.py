from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from apps.academics.models import GradeBoundary, TeacherAllocation
from apps.core import audit
from apps.core.context import get_current_tenant
from apps.students.models import StudentEnrolment
from apps.tenancy.permissions import has_permission

from .models import Assessment, Mark, PublishedResult


def accessible_assessments(member):
    authorize(member, permission="assessments.view")
    qs = Assessment.objects.select_related("subject", "class_group", "term", "policy")
    if member.role == "teacher":
        scope = Q(pk__in=[])
        allocations = TeacherAllocation.objects.filter(
            teacher=member, is_active=True, offering__is_active=True
        ).select_related("offering")
        for allocation in allocations:
            part = Q(
                class_group_id=allocation.class_group_id,
                subject_id=allocation.offering.subject_id,
                class_group__academic_year_id=allocation.offering.academic_year_id,
            )
            if allocation.term_id:
                part &= Q(term_id=allocation.term_id)
            scope |= part
        qs = qs.filter(scope)
    return qs


def profile_results(student, member):
    from apps.tenancy.services import has_module

    if not member or not has_permission(member, "assessments.view") or not has_module(student.tenant, "assessments"):
        return []
    authorize(member, permission="assessments.view")
    return (
        PublishedResult.objects.filter(student=student, assessment__in=accessible_assessments(member))
        .select_related("assessment__term")
        .order_by("-created_at")[:10]
    )


def authorize(member, assessment=None, permission="assessments.manage"):
    tenant = get_current_tenant()
    if not tenant or not member or member.tenant_id != tenant.pk or not has_permission(member, permission):
        raise PermissionDenied
    if assessment and assessment.tenant_id != tenant.pk:
        raise PermissionDenied
    if (
        assessment
        and member.role == "teacher"
        and not TeacherAllocation.objects.filter(
            teacher=member,
            class_group=assessment.class_group,
            offering__subject=assessment.subject,
            offering__academic_year=assessment.class_group.academic_year,
            is_active=True,
            offering__is_active=True,
        )
        .filter(Q(term=assessment.term) | Q(term__isnull=True))
        .exists()
    ):
        raise PermissionDenied


def roster(assessment):
    return StudentEnrolment.objects.filter(
        class_group=assessment.class_group, effective_from__lte=assessment.date
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=assessment.date))


@transaction.atomic
def save_marks(assessment, entries, member):
    authorize(member, assessment)
    assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
    authorize(member, assessment)
    if assessment.status != "draft":
        raise ValidationError("Only draft marks can be changed. Request a reviewed correction first.")
    students = {str(e.student_id): e.student for e in roster(assessment).select_related("student")}
    if len(entries) != len({str(e["student"]) for e in entries}):
        raise ValidationError("Duplicate student in marks submission.")
    for entry in entries:
        student_id = str(entry["student"])
        if student_id not in students:
            raise ValidationError("Student is not enrolled in this assessment class on its date.")
        mark, _ = Mark.objects.get_or_create(assessment=assessment, student=students[student_id])
        previous = {"score": str(mark.score), "exempt": mark.exempt, "comment": mark.comment}
        mark.score, mark.exempt, mark.comment = entry["score"], entry.get("exempt", False), entry.get("comment", "")
        mark.save()
        audit.record(
            "assessment.mark_saved",
            actor=member.user,
            obj=mark,
            changes={
                "before": previous,
                "after": {"score": str(mark.score), "exempt": mark.exempt, "comment": mark.comment},
            },
        )


def grade_for(percent, boundaries):
    matches = [b for b in boundaries if b.minimum_percent <= percent <= b.maximum_percent]
    if len(matches) != 1:
        raise ValidationError("Configure nonoverlapping grade boundaries covering every result before approval.")
    return matches[0].grade, matches[0].is_pass


@transaction.atomic
def transition(assessment, target, member, feedback=""):
    authorize(member, assessment, "assessments.manage" if target == "submitted" else "assessments.review")
    assessment = Assessment.objects.select_for_update().select_related("policy").get(pk=assessment.pk)
    authorize(member, assessment, "assessments.manage" if target == "submitted" else "assessments.review")
    allowed = {
        "draft": ["submitted"],
        "submitted": ["under_review", "draft"],
        "under_review": ["approved", "draft"],
        "approved": ["published", "draft"],
        "published": [],
    }
    if target not in allowed[assessment.status]:
        raise ValidationError("Invalid workflow transition.")
    if target == "draft" and not feedback.strip():
        raise ValidationError("Reviewer feedback is required to return marks for correction.")
    marks = {m.student_id: m for m in assessment.marks.select_related("student")}
    boundaries = list(GradeBoundary.objects.all())
    if target in ["submitted", "approved", "published"]:
        for enrolment in roster(assessment):
            mark = marks.get(enrolment.student_id)
            if (not mark or (mark.score is None and not mark.exempt)) and assessment.policy.missing == "block":
                raise ValidationError("Complete missing marks or explicitly exempt students before submission.")
            if target in ["approved", "published"] and (not mark or not mark.exempt):
                grade_for(
                    (
                        (mark.score if mark and mark.score is not None else Decimal(0)) / assessment.maximum_marks * 100
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    boundaries,
                )
    if target == "published":
        for enrolment in roster(assessment).select_related("student"):
            mark = marks.get(enrolment.student_id)
            exempt = bool(mark and mark.exempt)
            score = mark.score if mark and mark.score is not None else Decimal(0)
            percent = (score / assessment.maximum_marks * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            grade, passed = ("Exempt", None) if exempt else grade_for(percent, boundaries)
            PublishedResult.objects.create(
                assessment=assessment,
                student=enrolment.student,
                snapshot={
                    "title": assessment.title,
                    "student": enrolment.student.full_name,
                    "admission_number": enrolment.student.admission_number,
                    "subject": assessment.subject.name,
                    "term": str(assessment.term),
                    "class": str(assessment.class_group),
                    "score": str(score),
                    "maximum": str(assessment.maximum_marks),
                    "percent": str(percent),
                    "grade": grade,
                    "passed": passed,
                    "exempt": exempt,
                    "comment": mark.comment if mark else "",
                    "weight": str(assessment.weight),
                    "component": "examination" if assessment.kind == "examination" else "continuous",
                    "policy": {
                        "continuous": str(assessment.policy.continuous_weight),
                        "examination": str(assessment.policy.examination_weight),
                        "rankings": assessment.policy.rankings,
                        "boundaries": [
                            {
                                "grade": b.grade,
                                "minimum": str(b.minimum_percent),
                                "maximum": str(b.maximum_percent),
                                "passed": b.is_pass,
                            }
                            for b in boundaries
                        ],
                    },
                },
            )
    previous = assessment.status
    assessment.status, assessment.feedback = target, feedback
    assessment.save()
    audit.record(
        "assessment." + target,
        actor=member.user,
        obj=assessment,
        changes={"status": {"before": previous, "after": target}, "feedback": feedback},
    )
    return assessment


def subject_total(results):
    """Exempt assessments leave the denominator; absent required components block totals."""
    usable = [r.snapshot for r in results if not r.snapshot["exempt"]]
    if not usable:
        return None
    policies = {str(s["policy"]) for s in usable}
    if len(policies) != 1:
        return None
    policy = usable[0]["policy"]
    total = Decimal(0)
    included_weight = Decimal(0)
    for component in ["continuous", "examination"]:
        weight = Decimal(policy[component])
        if not weight:
            continue
        group = [s for s in usable if s["component"] == component]
        if not group:
            if any(r.snapshot["component"] == component and r.snapshot["exempt"] for r in results):
                continue
            return None
        denominator = sum(Decimal(s["weight"]) for s in group)
        total += sum(Decimal(s["percent"]) * Decimal(s["weight"]) for s in group) / denominator * weight / 100
        included_weight += weight
    if not included_weight:
        return None
    return (total * 100 / included_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def student_summary(results):
    groups = {}
    for result in results:
        groups.setdefault(result.assessment.subject_id, []).append(result)
    totals = [subject_total(group) for group in groups.values()]
    if not totals or any(value is None for value in totals):
        return None
    return (sum(totals) / len(totals)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def subject_grade(results):
    total = subject_total(results)
    if total is None:
        return "Incomplete / exempt"
    boundaries = results[0].snapshot["policy"].get("boundaries", [])
    matches = [b for b in boundaries if Decimal(b["minimum"]) <= total <= Decimal(b["maximum"])]
    return matches[0]["grade"] if len(matches) == 1 else "Unclassified"


def competition_rank(results, student_id):
    """Equal rounded averages share a rank; the next rank skips tied places (1,1,3)."""
    groups = {}
    for result in results:
        groups.setdefault(result.student_id, []).append(result)
    averages = {key: student_summary(value) for key, value in groups.items()}
    target_subjects = {r.assessment.subject_id for r in groups.get(student_id, [])}
    averages = {
        key: value
        for key, value in averages.items()
        if {r.assessment.subject_id for r in groups[key]} == target_subjects
    }
    average = averages.get(student_id)
    if average is None:
        return None
    return 1 + sum(value is not None and value > average for value in averages.values())
