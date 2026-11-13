import csv
from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.forms import formset_factory
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.core import audit
from apps.students.models import Student
from apps.tenancy.access import access_required

from . import services
from .forms import AssessmentForm, ExaminationForm, MarkForm, PolicyForm
from .models import Assessment, Examination, PublishedResult


def visible(request):
    return services.accessible_assessments(request.membership)


@access_required("assessments", "assessments.view")
@require_http_methods(["GET"])
def index(request):
    qs = visible(request)
    return render(request, "assessments/index.html", {"page": Paginator(qs, 30).get_page(request.GET.get("page"))})


@access_required("assessments", "assessments.manage")
@require_http_methods(["GET", "POST"])
def create(request):
    instance = Assessment(tenant=request.tenant)
    form = AssessmentForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        services.authorize(request.membership, form.instance)
        with transaction.atomic():
            form.save()
            audit.record("assessment.created", actor=request.user, obj=form.instance)
        return redirect("assessments:detail", pk=form.instance.pk)
    return render(request, "assessments/form.html", {"form": form, "title": "Create assessment"})


@access_required("assessments", "assessments.review")
@require_http_methods(["GET", "POST"])
def policy(request):
    from .models import ResultPolicy

    form = PolicyForm(request.POST or None, instance=ResultPolicy(tenant=request.tenant))
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            audit.record("assessment.policy_created", actor=request.user, obj=form.instance)
        return redirect("assessments:index")
    return render(request, "assessments/form.html", {"form": form, "title": "Create result policy"})


@access_required("assessments", "assessments.view")
@require_http_methods(["GET", "POST"])
def detail(request, pk):
    assessment = get_object_or_404(visible(request), pk=pk)
    existing = {m.student_id: m for m in assessment.marks.all()}
    initial = []
    names = []
    for enrolment in (
        services.roster(assessment).select_related("student").order_by("student__last_name", "student__first_name")
    ):
        mark = existing.get(enrolment.student_id)
        initial.append(
            {
                "student": enrolment.student_id,
                "score": mark.score if mark else None,
                "exempt": mark.exempt if mark else False,
                "comment": mark.comment if mark else "",
            }
        )
        names.append(enrolment.student.full_name)
    MarkSet = formset_factory(MarkForm, extra=0, max_num=2000, validate_max=True, absolute_max=2000)
    formset = MarkSet(
        request.POST if request.method == "POST" and request.POST.get("action") == "marks" else None, initial=initial
    )
    if request.method == "POST":
        try:
            if request.POST.get("action") == "marks":
                if formset.is_valid():
                    services.save_marks(assessment, formset.cleaned_data, request.membership)
                else:
                    raise ValidationError("Correct the invalid marks below.")
            else:
                services.transition(
                    assessment, request.POST.get("target"), request.membership, request.POST.get("feedback", "")
                )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Assessment saved.")
            return redirect("assessments:detail", pk=pk)
    return render(
        request,
        "assessments/detail.html",
        {
            "assessment": assessment,
            "formset": formset,
            "rows": list(zip(names, formset, strict=False)),
            "targets": ["submitted", "under_review", "approved", "published", "draft"],
            "history": assessment_history(request, assessment),
        },
    )


def assessment_history(request, assessment):
    from apps.core.models import AuditEvent

    mark_ids = [str(value) for value in assessment.marks.values_list("pk", flat=True)]
    return AuditEvent.objects.filter(tenant=request.tenant, object_id__in=[str(assessment.pk), *mark_ids]).order_by(
        "-created_at"
    )[:30]


@access_required("assessments", "assessments.view")
@require_http_methods(["GET"])
def examinations(request):
    qs = (
        Examination.objects.filter(assessment__in=visible(request))
        .select_related("assessment__class_group", "invigilator__user")
        .order_by("starts_at")
    )
    return render(
        request, "assessments/examinations.html", {"page": Paginator(qs, 30).get_page(request.GET.get("page"))}
    )


@access_required("assessments", "assessments.review")
@require_http_methods(["GET", "POST"])
def schedule(request, pk):
    assessment = get_object_or_404(Assessment, pk=pk)
    exam = Examination.objects.filter(assessment=assessment).first() or Examination(
        tenant=request.tenant, assessment=assessment
    )
    form = ExaminationForm(request.POST or None, instance=exam)
    if request.method == "POST":
        # Serialise scheduling within one school, including the empty-calendar case.
        with transaction.atomic():
            from apps.tenancy.models import Tenant

            Tenant.objects.select_for_update().get(pk=request.tenant.pk)
            if form.is_valid():
                form.save()
                audit.record("assessment.examination_scheduled", actor=request.user, obj=exam)
                return redirect("assessments:detail", pk=pk)
    return render(request, "assessments/form.html", {"form": form, "title": "Schedule examination"})


def published(request):
    return PublishedResult.objects.filter(assessment__in=visible(request)).select_related("assessment__term", "student")


@access_required("assessments", "assessments.view")
@require_http_methods(["GET"])
def results(request, student_id=None):
    qs = published(request)
    student = None
    if student_id:
        student = get_object_or_404(Student, pk=student_id)
        qs = qs.filter(student=student)
    return render(
        request,
        "assessments/results.html",
        {"student": student, "page": Paginator(qs.order_by("-created_at"), 50).get_page(request.GET.get("page"))},
    )


def safe_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


@access_required("assessments", "assessments.view")
@require_http_methods(["GET"])
def export(request, pk):
    assessment = get_object_or_404(visible(request), pk=pk, status="published")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="assessment-results.csv"'
    writer = csv.writer(response)
    writer.writerow(["Admission number", "Student", "Subject", "Score", "Maximum", "Percentage", "Grade", "Exempt"])
    for result in PublishedResult.objects.filter(assessment=assessment).iterator(chunk_size=500):
        s = result.snapshot
        writer.writerow(
            [
                safe_cell(s[k])
                for k in ["admission_number", "student", "subject", "score", "maximum", "percent", "grade", "exempt"]
            ]
        )
    audit.record("assessment.results_exported", actor=request.user, obj=assessment)
    return response


@access_required("assessments", "assessments.view")
@require_http_methods(["GET"])
def analytics(request):
    groups = defaultdict(list)
    for result in published(request).iterator(chunk_size=500):
        s = result.snapshot
        if not s["exempt"]:
            groups[(s["term"], s["class"], s["subject"])].append(s)
    rows = []
    for key, marks in sorted(groups.items()):
        count = len(marks)
        distribution = defaultdict(int)
        for m in marks:
            distribution[m["grade"]] += 1
        rows.append(
            (
                key,
                count,
                (sum(Decimal(m["percent"]) for m in marks) / count).quantize(Decimal(".01")),
                (Decimal(sum(m["passed"] for m in marks)) * 100 / count).quantize(Decimal(".01")),
                dict(distribution),
            )
        )
    return render(request, "assessments/analytics.html", {"rows": rows})


@access_required("assessments", "assessments.view")
@require_http_methods(["GET"])
def report(request, student_id, term_id):
    from .pdf import report_pdf

    student = get_object_or_404(Student, pk=student_id)
    from apps.academics.models import Term

    term = get_object_or_404(Term, pk=term_id)
    rows = list(published(request).filter(student=student, assessment__term=term))
    if not rows:
        from django.http import Http404

        raise Http404
    response = HttpResponse(report_pdf(request.tenant, student, term, rows), content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="report-card.pdf"'
    response["Cache-Control"] = "private, no-store"
    audit.record("assessment.report_downloaded", actor=request.user, obj=student, term=term.pk)
    return response


@access_required("assessments", "assessments.review")
@require_http_methods(["GET", "POST"])
def report_comment(request, student_id, term_id):
    from apps.academics.models import Term

    from .forms import ReportCommentForm
    from .models import ReportComment

    student = get_object_or_404(Student, pk=student_id)
    term = get_object_or_404(Term, pk=term_id)
    instance = ReportComment.objects.filter(student=student, term=term).first() or ReportComment(
        tenant=request.tenant, student=student, term=term
    )
    form = ReportCommentForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            before = ReportComment.objects.filter(pk=instance.pk).values_list("headmaster_comment", flat=True).first()
            form.save()
            audit.record(
                "assessment.report_comment_saved",
                actor=request.user,
                obj=instance,
                changes={"before": before, "after": instance.headmaster_comment},
            )
        return redirect("assessments:student-results", student_id=student_id)
    return render(request, "assessments/form.html", {"form": form, "title": "Headmaster comment: " + student.full_name})


@access_required("assessments", "assessments.review")
@require_http_methods(["GET", "POST"])
def configuration(request, kind):
    from django.http import Http404

    from apps.academics.models import AssessmentCategory, GradeBoundary

    from .forms import BoundaryForm, CategoryForm

    if kind not in ["categories", "grades"]:
        raise Http404
    model, form_type = (AssessmentCategory, CategoryForm) if kind == "categories" else (GradeBoundary, BoundaryForm)
    form = form_type(request.POST or None, instance=model(tenant=request.tenant))
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            audit.record("assessment.configuration_created", actor=request.user, obj=form.instance)
        return redirect("assessments:index")
    return render(request, "assessments/form.html", {"form": form, "title": "Configure " + kind})
