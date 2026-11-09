from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Prefetch, Q, Value
from django.db.models.functions import Concat
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.core import audit
from apps.core.models import AuditEvent
from apps.tenancy.access import access_required
from apps.tenancy.permissions import has_permission

from . import services
from .forms import DirectoryFilterForm, DocumentForm, EnrolForm, GuardianForm, StatusForm, StudentForm
from .models import Student, StudentDocument, StudentEnrolment


@access_required("students", "students.view")
@require_GET
def student_list(request):
    filters = DirectoryFilterForm(request.GET)
    qs = Student.objects.annotate(search_name=Concat("first_name", Value(" "), "last_name"))
    today = timezone.localdate()
    current = StudentEnrolment.objects.filter(effective_from__lte=today).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=today)
    ).select_related("class_group__grade", "class_group__academic_year")
    qs = qs.prefetch_related(Prefetch("enrolments", queryset=current, to_attr="current_enrolments"))
    if filters.is_valid():
        data = filters.cleaned_data
        if data.get("q"):
            qs = qs.filter(Q(search_name__icontains=data["q"]) | Q(admission_number__icontains=data["q"]))
        if data.get("status"):
            qs = qs.filter(status=data["status"])
        if data.get("class_group"):
            # Same enrolment must match class, year and date boundaries.
            matches = current.filter(student_id=OuterRef("pk"), class_group=data["class_group"])
            if data.get("academic_year"):
                matches = matches.filter(class_group__academic_year=data["academic_year"])
            qs = qs.filter(Exists(matches))
        elif data.get("academic_year"):
            qs = qs.filter(enrolments__class_group__academic_year=data["academic_year"],
                           enrolments__tenant=request.tenant).distinct()
    else:
        qs = qs.none()
    page = Paginator(qs.order_by("last_name", "first_name", "pk"), 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    # Preserve the established rows-only response for existing HTMX callers.
    template = "students/_rows.html" if request.headers.get("HX-Request") else "students/list.html"
    return render(request, template, {
        "page": page, "filters": filters, "filter_query": params.urlencode(),
        "can_manage": has_permission(request.membership, "students.manage"),
    })


@access_required("students", "students.manage")
@require_http_methods(["GET", "POST"])
def student_create(request):
    data = request.POST if request.method == "POST" else None
    form = StudentForm(data, request.FILES or None)
    guardian_form = GuardianForm(data, prefix="guardian", optional=True)
    if request.method == "POST":
        valid_student, valid_guardian = form.is_valid(), guardian_form.is_valid()
        if valid_student and valid_guardian:
            try:
                student = services.create_student(
                    actor=request.user, request=request, **form.cleaned_data,
                    guardian_data=guardian_form.cleaned_data if guardian_form.has_contact else None,
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, f"Learner created. Admission number {student.admission_number}.")
                return redirect("students:detail", pk=student.pk)
    return render(request, "students/form.html", {"form": form, "guardian_form": guardian_form, "title": "Add learner"})


@access_required("students", "students.manage")
@require_http_methods(["GET", "POST"])
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = StudentForm(request.POST if request.method == "POST" else None, request.FILES or None, instance=student)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_student(student, actor=request.user, request=request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, "Student record updated.")
            return redirect("students:detail", pk=student.pk)
    return render(request, "students/form.html", {"form": form, "student": student, "title": "Edit learner"})


@access_required("students", "students.view")
@require_http_methods(["GET", "POST"])
def student_detail(request, pk):
    student = get_object_or_404(Student, pk=pk)
    forms = {"enrol": EnrolForm(), "guardian": GuardianForm(),
             "status": StatusForm(initial={"status": student.status}), "document": DocumentForm()}
    can_manage = has_permission(request.membership, "students.manage")
    if request.method == "POST":
        if not can_manage:
            return render(request, "tenancy/forbidden.html", status=403)
        action = request.POST.get("action")
        if action not in forms:
            return render(request, "tenancy/forbidden.html", status=400)
        form_type = {"enrol": EnrolForm, "guardian": GuardianForm, "status": StatusForm, "document": DocumentForm}[action]
        form = form_type(request.POST, request.FILES) if action == "document" else form_type(request.POST)
        forms[action] = form
        if form.is_valid():
            try:
                if action == "enrol":
                    services.enrol_student(student, actor=request.user, request=request, **form.cleaned_data)
                elif action == "guardian":
                    services.add_guardian(student, actor=request.user, request=request, **form.cleaned_data)
                elif action == "status":
                    services.change_student_status(student, actor=request.user, request=request, **form.cleaned_data)
                else:
                    services.upload_document(student, actor=request.user, request=request, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, "Student record updated.")
                return redirect("students:detail", pk=student.pk)
    today = timezone.localdate()
    enrolments = StudentEnrolment.objects.filter(student=student).select_related("class_group__grade", "class_group__academic_year")
    current = enrolments.filter(effective_from__lte=today).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=today)
    ).first()
    activity = AuditEvent.objects.filter(tenant=request.tenant).filter(
        Q(object_type="Student", object_id=str(student.pk)) | Q(metadata__student=str(student.pk))
    ).order_by("-created_at", "-pk")
    return render(request, "students/detail.html", {
        "student": student, "enrolments": enrolments, "current_enrolment": current,
        "guardian_links": student.guardian_links.filter(tenant=request.tenant).select_related("guardian"),
        "enrol_form": forms["enrol"], "guardian_form": forms["guardian"],
        "status_form": forms["status"], "document_form": forms["document"],
        "documents": StudentDocument.objects.filter(student=student) if can_manage else [],
        "activity": Paginator(activity, 20).get_page(request.GET.get("activity_page")),
        "can_manage": can_manage,
    })


@access_required("students", "students.manage")
@require_GET
def document_download(request, pk, document_id):
    document = get_object_or_404(StudentDocument, pk=document_id, student_id=pk)
    try:
        stream = document.file.storage.open(document.file.name, "rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404 from exc
    audit.record("student.document_downloaded", actor=request.user, obj=document,
                 request=request, student=pk)
    response = FileResponse(stream, as_attachment=True, filename=document.file.name.rsplit("/", 1)[-1],
                            content_type="application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
