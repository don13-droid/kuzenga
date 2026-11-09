from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Value
from django.db.models.functions import Concat
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.core import audit
from apps.core.models import AuditEvent
from apps.tenancy.permissions import has_permission

from . import services
from .access import admissions_access
from .forms import (
    ApplicationDocumentForm,
    ApplicationFilterForm,
    ApplicationForm,
    EnrolmentForm,
    ReviewNoteForm,
    TransitionForm,
)
from .models import ApplicationDocument, StudentApplication


def _permissions(request):
    permissions = {f"can_{action}": has_permission(request.membership, f"admissions.{action}")
                   for action in ("manage", "review", "enrol")}
    permissions["can_enrol"] = permissions["can_enrol"] and has_permission(request.membership, "students.manage")
    return permissions


@admissions_access("admissions.view")
@require_GET
def dashboard(request):
    grouped = dict(StudentApplication.objects.order_by().values_list("status").annotate(total=Count("pk")))
    cards = [("total", "Total applications", sum(grouped.values()))]
    cards += [(status, "Pending applications" if status == "submitted" else label, grouped.get(status, 0))
              for status, label in StudentApplication.Status.choices]
    recent = AuditEvent.objects.filter(tenant=request.tenant, action__startswith="admissions.").select_related("actor")[:20]
    return render(request, "admissions/dashboard.html", {"cards": cards, "recent": recent, **_permissions(request)})


@admissions_access("admissions.view")
@require_GET
def application_list(request):
    form = ApplicationFilterForm(request.GET)
    records = StudentApplication.objects.select_related("intended_year", "intended_grade").annotate(
        applicant_name=Concat("first_name", Value(" "), "last_name"),
        contact_name=Concat("guardian_first_name", Value(" "), "guardian_last_name"),
    )
    if form.is_valid():
        data = form.cleaned_data
        if data.get("q"):
            records = records.filter(Q(applicant_name__icontains=data["q"]) | Q(reference__icontains=data["q"])
                                     | Q(contact_name__icontains=data["q"]))
        for field, key in (("status", "status"), ("intended_grade", "grade"), ("intended_year", "academic_year")):
            if data.get(key):
                records = records.filter(**{field: data[key]})
    else:
        records = records.none()
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "admissions/list.html", {"filters": form, "filter_query": params.urlencode(),
        "page": Paginator(records, 25).get_page(request.GET.get("page")), **_permissions(request)})


@admissions_access("admissions.manage")
@require_http_methods(["GET", "POST"])
def application_create(request):
    data = request.POST if request.method == "POST" else None
    form = ApplicationForm(data)
    document_form = ApplicationDocumentForm(data, request.FILES or None, prefix="document")
    if request.method == "POST":
        valid = form.is_valid()
        has_document = bool(request.POST.get("document-title", "").strip() or request.FILES.get("document-file"))
        valid_document = document_form.is_valid() if has_document else True
        if valid and valid_document:
            values = form.cleaned_data.copy()
            values.pop("reason", None)
            values.pop("expected_updated_at", None)
            try:
                application = services.create_application(actor=request.user, request=request, data=values,
                    submit=request.POST.get("submit") == "yes",
                    document_data=document_form.cleaned_data if has_document else None)
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, "Application saved.")
                return redirect("admissions:detail", pk=application.pk)
    return render(request, "admissions/form.html", {"form": form, "document_form": document_form, "creating": True})


@admissions_access("admissions.manage")
@require_http_methods(["GET", "POST"])
def application_edit(request, pk):
    application = get_object_or_404(StudentApplication, pk=pk)
    if application.status not in services.EDITABLE_STATUSES:
        raise PermissionDenied
    form = ApplicationForm(request.POST if request.method == "POST" else None, instance=application)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        reason, expected = data.pop("reason"), data.pop("expected_updated_at")
        try:
            services.update_application(application, actor=request.user, request=request, data=data,
                                        expected_updated_at=expected, reason=reason)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, "Application updated.")
            return redirect("admissions:detail", pk=pk)
    return render(request, "admissions/form.html", {"form": form, "application": application})


@admissions_access("admissions.view")
@require_http_methods(["GET", "POST"])
def application_detail(request, pk):
    application = get_object_or_404(StudentApplication.objects.select_related(
        "intended_year", "intended_grade", "intended_class", "student", "guardian"), pk=pk)
    permissions = _permissions(request)
    transition = TransitionForm(application=application, can_submit=permissions["can_manage"], can_review=permissions["can_review"])
    note_form, document_form = ReviewNoteForm(), ApplicationDocumentForm(prefix="document")
    status_code = 200
    if request.method == "POST":
        action = request.POST.get("action")
        allowed = {"transition": permissions["can_manage"] if request.POST.get("target") == "submitted" else permissions["can_review"],
                   "note": permissions["can_review"], "document": permissions["can_manage"]}
        if not allowed.get(action):
            raise PermissionDenied
        if action == "transition":
            form = transition = TransitionForm(request.POST, application=application,
                can_submit=permissions["can_manage"], can_review=permissions["can_review"])
        elif action == "note":
            form = note_form = ReviewNoteForm(request.POST)
        else:
            form = document_form = ApplicationDocumentForm(request.POST, request.FILES, prefix="document")
        if form.is_valid():
            try:
                if action == "transition":
                    application.updated_at = form.cleaned_data["expected_updated_at"]
                    services.transition_application(application, actor=request.user, request=request,
                        target=form.cleaned_data["target"], reason=form.cleaned_data["reason"])
                elif action == "note":
                    services.add_review_note(application, actor=request.user, request=request, **form.cleaned_data)
                else:
                    services.upload_document(application, actor=request.user, request=request, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, "Application history updated.")
                return redirect("admissions:detail", pk=pk)
        status_code = 400
    return render(request, "admissions/detail.html", {
        "application": application, "transition_form": transition, "note_form": note_form,
        "document_form": document_form, "documents": ApplicationDocument.objects.filter(application=application),
        "history": Paginator(services.application_history(application, actor=request.user), 20).get_page(request.GET.get("history_page")),
        "editable": application.status in services.EDITABLE_STATUSES, **permissions,
    }, status=status_code)


@admissions_access("admissions.enrol")
@require_http_methods(["GET", "POST"])
def application_enrol(request, pk):
    application = get_object_or_404(StudentApplication.objects.select_related("intended_year", "intended_grade", "student"), pk=pk)
    if not has_permission(request.membership, "students.manage"):
        raise PermissionDenied
    if application.status not in (StudentApplication.Status.ACCEPTED, StudentApplication.Status.ENROLLED):
        raise PermissionDenied
    form = EnrolmentForm(request.POST if request.method == "POST" else None, application=application)
    if request.method == "POST":
        if application.student_id:
            return redirect("admissions:detail", pk=pk)
        if form.is_valid():
            try:
                services.enrol_application(application, actor=request.user, request=request, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, "Application enrolled into Student Management.")
                return redirect("admissions:detail", pk=pk)
    return render(request, "admissions/enrol.html", {"application": application, "form": form})


@admissions_access("admissions.view")
@require_GET
def document_download(request, pk, document_id):
    document = get_object_or_404(ApplicationDocument, pk=document_id, application_id=pk)
    try:
        stream = document.file.storage.open(document.file.name, "rb")
    except OSError as exc:
        raise Http404 from exc
    audit.record("admissions.document_downloaded", actor=request.user, obj=document.application,
                 tenant=request.tenant, request=request)
    response = FileResponse(stream, as_attachment=True, filename=document.file.name.rsplit("/", 1)[-1],
                            content_type="application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
