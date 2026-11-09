from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.models import AuditEvent
from apps.students.models import StudentEnrolment
from apps.tenancy.permissions import has_permission

from . import forms, models, services
from .access import academic_access

RESOURCES = {
    "years": {
        "model": models.AcademicYear,
        "form": forms.AcademicYearForm,
        "title": "Academic years",
        "columns": [
            ("Name", "name"),
            ("Starts", "start_date"),
            ("Ends", "end_date"),
            ("Current", "is_current"), ("Status", "get_status_display"),
        ],
    },
    "terms": {
        "model": models.Term,
        "form": forms.TermForm,
        "title": "Terms",
        "related": ["academic_year"],
        "columns": [
            ("Year", "academic_year"),
            ("Term", "name"),
            ("Starts", "start_date"),
            ("Ends", "end_date"), ("Current", "is_current"),
        ],
    },
    "grades": {
        "model": models.Grade,
        "form": forms.GradeForm,
        "title": "Grades / levels",
        "columns": [("Name", "name"), ("Order", "level_order")],
    },
    "classes": {
        "model": models.ClassGroup,
        "form": forms.ClassGroupForm,
        "title": "Classes",
        "related": ["academic_year", "grade"],
        "columns": [("Year", "academic_year"), ("Grade", "grade"), ("Class", "name"), ("Students", "student_count"), ("Capacity", "capacity"), ("Utilisation", "utilisation"), ("Active", "is_active")],
    },
    "subjects": {
        "model": models.Subject,
        "form": forms.SubjectForm,
        "title": "Subjects",
        "columns": [("Code", "code"), ("Name", "name"), ("Active", "is_active")],
    },
    "offerings": {"model": models.SubjectOffering, "form": forms.SubjectOfferingForm, "title": "Curriculum offerings",
        "related": ["academic_year", "grade", "subject", "class_group__grade", "class_group__academic_year"],
        "columns": [("Year", "academic_year"), ("Subject", "subject"), ("Grade", "grade"), ("Class (blank = whole grade)", "class_group"), ("Compulsory", "is_compulsory"), ("Active", "is_active")]},
    "allocations": {"model": models.TeacherAllocation, "form": forms.TeacherAllocationForm, "title": "Teacher allocations",
        "related": ["offering__subject", "offering__grade", "offering__academic_year", "offering__class_group__grade", "offering__class_group__academic_year", "class_group__grade", "class_group__academic_year", "teacher__user", "teacher__tenant", "term__academic_year"],
        "columns": [("Offering", "offering"), ("Class", "class_group"), ("Teacher", "teacher"), ("Term (blank = whole year)", "term"), ("Active", "is_active")]},
}



def _context(request):
    return {"academic_navigation": [(kind, cfg["title"]) for kind, cfg in RESOURCES.items()],
            "can_manage": has_permission(request.membership, "academics.manage")}


def _roster(on_date):
    return StudentEnrolment.objects.filter(student__status="active", effective_from__lte=on_date).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=on_date)
    )


def _class_counts(queryset):
    today = timezone.localdate()
    return queryset.annotate(student_count=Count("enrolments__student", distinct=True,
        filter=Q(enrolments__student__status="active", enrolments__effective_from__lte=today)
        & (Q(enrolments__effective_to__isnull=True) | Q(enrolments__effective_to__gte=today))))


@academic_access("academics.view")
@require_GET
def overview(request):
    today = timezone.localdate()
    year = models.AcademicYear.objects.filter(is_current=True).first()
    classes = _class_counts(models.ClassGroup.objects.select_related("grade", "academic_year"))
    approaching = [group for group in classes.filter(is_active=True) if group.capacity is not None
                   and (not year or group.academic_year_id == year.pk) and group.student_count >= group.capacity * .8]
    return render(request, "academics/overview.html", {
        "cards": [{"kind": kind, "title": cfg["title"], "count": cfg["model"].objects.count()} for kind, cfg in RESOURCES.items() if kind != "allocations" or has_permission(request.membership, "academics.manage")],
        "current_year": year, "current_term": models.Term.objects.filter(is_current=True).first(),
        "placement_count": _roster(today).values("student_id").distinct().count(),
        "near_capacity": approaching[:20],
        "recent": AuditEvent.objects.filter(tenant=request.tenant, action__startswith="academic.")[:20],
        **_context(request),
    })


@academic_access("academics.view")
@require_GET
def resource_list(request, kind):
    cfg = get_object_or_404_cfg(kind)
    qs = cfg["model"].objects.all()
    if cfg.get("related"):
        qs = qs.select_related(*cfg["related"])
    if kind == "allocations" and not has_permission(request.membership, "academics.manage"):
        qs = qs.filter(teacher__user=request.user)
    if kind == "classes":
        qs = _class_counts(qs)
    form = forms.ResourceFilterForm(request.GET, kind=kind,
        teacher_user=request.user if not has_permission(request.membership, "academics.manage") else None)
    if form.is_valid():
        data = form.cleaned_data
        if data.get("q"):
            search = Q()
            fields = {"subjects": ["code", "name", "description"], "classes": ["code", "name", "grade__name"],
                      "offerings": ["subject__code", "subject__name", "grade__name"],
                      "allocations": ["teacher__user__full_name", "teacher__user__email", "offering__subject__name", "class_group__name"]}.get(kind, ["name"])
            for field in fields:
                search |= Q(**{f"{field}__icontains": data["q"]})
            qs = qs.filter(search)
        if data.get("academic_year"):
            field = "offering__academic_year" if kind == "allocations" else "academic_year"
            qs = qs.filter(**{field: data["academic_year"]})
        if data.get("active"):
            qs = qs.filter(is_active=data["active"] == "yes")
        if data.get("teacher"):
            qs = qs.filter(teacher=data["teacher"])
    else:
        qs = qs.none()
    ordering = list(cfg["model"]._meta.ordering or [])
    if "pk" not in ordering:
        ordering.append("pk")
    page = Paginator(qs.order_by(*ordering), 25).get_page(request.GET.get("page"))
    rows = []
    for obj in page:
        if kind == "classes":
            obj.utilisation = f"{round(obj.student_count * 100 / obj.capacity)}%" if obj.capacity else ("Unlimited" if obj.capacity is None else "No places")
        cells = [getattr(obj, attr) for _, attr in cfg["columns"]]
        rows.append({"object": obj, "cells": [value() if callable(value) else value for value in cells]})
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "academics/list.html", {"kind": kind, "title": cfg["title"], "rows": rows,
        "headers": [label for label, _ in cfg["columns"]], "filters": form, "page": page,
        "filter_query": params.urlencode(), **_context(request)})


@academic_access("academics.manage")
@require_http_methods(["GET", "POST"])
def resource_create(request, kind, pk=None):
    cfg = get_object_or_404_cfg(kind)
    instance = get_object_or_404(cfg["model"], pk=pk) if pk else None
    form = cfg["form"](request.POST if request.method == "POST" else None, instance=instance)
    if request.method == "POST" and form.is_valid():
        try:
            services.save_record(form.save(commit=False), actor=request.user, request=request,
                                 expected_updated_at=form.cleaned_data.get("expected_updated_at"))
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"{cfg['title']}: saved.")
            return redirect("academics:list", kind=kind)
    return render(request, "academics/form.html", {"form": form, "title": f"{'Edit' if pk else 'Add'}: {cfg['title']}", "kind": kind, **_context(request)})


@academic_access("academics.manage")
@require_POST
def resource_toggle(request, kind, pk):
    cfg = get_object_or_404_cfg(kind)
    if kind not in ("offerings", "allocations"):
        raise PermissionDenied
    record = get_object_or_404(cfg["model"], pk=pk)
    if request.POST.get("action") != "deactivate":
        raise PermissionDenied
    record.is_active = False
    services.save_record(record, actor=request.user, request=request)
    messages.success(request, "Record deactivated; history retained.")
    return redirect("academics:list", kind=kind)


@academic_access("academics.view")
@require_GET
def class_detail(request, pk):
    group = get_object_or_404(models.ClassGroup.objects.select_related("academic_year", "grade", "class_teacher__user"), pk=pk)
    roster = _roster(timezone.localdate()).filter(class_group=group).select_related("student")
    offerings = models.SubjectOffering.objects.filter(academic_year=group.academic_year, grade=group.grade, is_active=True).filter(
        Q(class_group=group) | Q(class_group__isnull=True)
    ).select_related("subject")
    allocations = models.TeacherAllocation.objects.filter(class_group=group).select_related("teacher__user", "offering__subject", "term")
    if not has_permission(request.membership, "academics.manage"):
        allocations = allocations.filter(teacher__user=request.user)
    return render(request, "academics/class_detail.html", {"group": group, "student_count": roster.values("student_id").distinct().count(),
        "students": Paginator(roster, 25).get_page(request.GET.get("page")) if has_permission(request.membership, "students.view") else [],
        "offerings": offerings, "allocations": allocations, **_context(request)})


@academic_access("academics.manage")
@require_http_methods(["GET", "POST"])
def progression(request):
    if not has_permission(request.membership, "students.manage"):
        raise PermissionDenied
    form = forms.ProgressionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            results = services.progress_students(actor=request.user, request=request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"Placement recorded for {len(results)} students.")
            return redirect("academics:progression")
    return render(request, "academics/progression.html", {"form": form, **_context(request)})


def get_object_or_404_cfg(kind):
    from django.http import Http404
    if kind not in RESOURCES:
        raise Http404
    return RESOURCES[kind]
