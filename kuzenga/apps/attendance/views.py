from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup
from apps.tenancy.access import access_required
from apps.tenancy.configuration_services import ensure_tenant_configuration

from . import services
from .models import AttendanceSession


@access_required("attendance", "attendance.view")
def today(request):
    on_date = timezone.localdate()
    sessions = {s.class_group_id: s for s in AttendanceSession.objects.filter(date=on_date)}
    classes = ClassGroup.objects.select_related("grade", "academic_year").filter(
        academic_year__is_current=True
    )
    rows = [(c, sessions.get(c.id)) for c in classes]
    return render(request, "attendance/today.html", {"rows": rows, "on_date": on_date})


@access_required("attendance", "attendance.take_register")
def register(request, class_id):
    class_group = get_object_or_404(ClassGroup, pk=class_id)  # tenant-scoped
    configuration = ensure_tenant_configuration(class_group.tenant)
    choices = [(item["code"], item["label"]) for item in configuration.attendance_statuses]
    on_date = timezone.localdate()
    session = services.open_register(class_group, on_date)

    if request.method == "POST" and session.status == AttendanceSession.Status.OPEN:
        statuses = {k[7:]: v for k, v in request.POST.items() if k.startswith("status_")}
        notes = {k[5:]: v for k, v in request.POST.items() if k.startswith("note_")}
        try:
            services.submit_register(
                session,
                statuses,
                notes,
                actor=request.user,
                valid_statuses=(code for code, _label in choices),
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Register submitted.")
            return redirect("attendance:today")

    records = session.records.select_related("student")
    status_labels = dict(choices)
    record_rows = [
        (record, status_labels.get(record.status, record.get_status_display()))
        for record in records
    ]
    ctx = {
        "class_group": class_group,
        "session": session,
        "record_rows": record_rows,
        "on_date": on_date,
        "choices": choices,
        "late_arrival_threshold_minutes": configuration.late_arrival_threshold_minutes,
    }
    return render(request, "attendance/register.html", ctx)
