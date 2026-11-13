"""Small paginated PDF writer using PDF's standard Helvetica font (no runtime dependency)."""

from collections import defaultdict
from decimal import Decimal
from io import BytesIO
from textwrap import wrap

from .services import competition_rank, subject_grade, subject_total


def report_pdf(tenant, student, term, results):
    from apps.attendance.models import AttendanceRecord

    from .models import Assessment, PublishedResult, ReportComment

    groups = defaultdict(list)
    for result in results:
        groups[result.snapshot["subject"]].append(result)
    lines = [
        tenant.name,
        "ACADEMIC REPORT CARD",
        str(term),
        results[0].snapshot["student"],
        "Admission number: " + results[0].snapshot["admission_number"],
        "",
    ]
    totals = []
    pending_subjects = set(
        Assessment.objects.filter(term=term, class_group_id__in={r.assessment.class_group_id for r in results})
        .exclude(status="published")
        .values_list("subject_id", flat=True)
    )
    for subject, records in sorted(groups.items()):
        total = None if records[0].assessment.subject_id in pending_subjects else subject_total(records)
        if total is not None:
            totals.append(total)
        lines.append(
            subject
            + " | Weighted percentage: "
            + (str(total) + " | " + subject_grade(records) if total is not None else "Incomplete / exempt")
        )
        for record in records:
            s = record.snapshot
            lines.extend(
                wrap(
                    f"  {s['title']}: {s['percent']}% | {s['grade']} | Teacher: {s['comment'] or 'No comment recorded'}",
                    90,
                )
            )
    lines += [
        "",
        "Average of complete subjects: "
        + (str((sum(totals) / len(totals)).quantize(Decimal(".01"))) if totals else "Unavailable"),
    ]
    attendance = AttendanceRecord.objects.filter(
        student=student,
        session__date__gte=term.start_date,
        session__date__lte=term.end_date,
        session__status="submitted",
    )
    counts = defaultdict(int)
    for status in attendance.values_list("status", flat=True):
        counts[status] += 1
    lines += [
        "Attendance (submitted registers): "
        + (", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "Not available")
    ]
    if results and not pending_subjects and all(r.snapshot["policy"]["rankings"] for r in results):
        class_ids = {r.assessment.class_group_id for r in results}
        peers = PublishedResult.objects.filter(
            assessment__term=term, assessment__class_group_id__in=class_ids
        ).select_related("assessment")
        lines.append("Class rank (competition ties): " + str(competition_rank(peers, student.pk) or "Incomplete"))
    comment = ReportComment.objects.filter(student=student, term=term).first()
    lines.extend(wrap("Headmaster comments: " + (comment.headmaster_comment if comment else "Not recorded"), 90))
    lines.append("Signature: __________________  Date: ________________")
    pages = [lines[i : i + 43] for i in range(0, len(lines), 43)]
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    logo_resource = ""
    if tenant.logo:
        from PIL import Image

        try:
            with tenant.logo.open("rb") as source:
                image = Image.open(source).convert("RGB")
                image.thumbnail((240, 240))
                buffer = BytesIO()
                image.save(buffer, format="JPEG")
                data = buffer.getvalue()
                objects.append(
                    f"<< /Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n".encode()
                    + data
                    + b"\nendstream"
                )
                logo_resource = "/XObject << /Logo 4 0 R >>"
        except (FileNotFoundError, OSError):
            pass  # The school name remains the brand if stored artwork is unavailable.
    kids = []
    for number, page in enumerate(pages, 1):
        page_id = len(objects) + 1
        kids.append(f"{page_id} 0 R")
        commands = [
            "0.055 0.10 0.23 rg 0 760 595 82 re f",
            "0.78 0.62 0.22 rg 0 752 595 8 re f",
            "BT /F1 12 Tf 36 730 Td 16 TL 0.055 0.10 0.23 rg",
        ]
        for line in page + [f"Page {number} of {len(pages)}"]:
            escaped = (
                line.replace("\r", " ").replace("\n", " ").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            )
            commands.append(f"({escaped}) Tj T*")
        commands.append("ET")
        if logo_resource:
            commands.append("q 58 0 0 58 500 772 cm /Logo Do Q")
        stream = "\n".join(commands).encode("cp1252", errors="replace")
        objects += [
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> {logo_resource} >> /Contents {page_id + 1} 0 R >>".encode(),
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        ]
    objects[1] = f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(kids)}] >>".encode()
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode())
    return bytes(output)
