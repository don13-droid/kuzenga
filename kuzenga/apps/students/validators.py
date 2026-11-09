from pathlib import Path

from django.core.exceptions import ValidationError

from apps.core.validators import validate_uploaded_image

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def validate_student_document(upload):
    if not upload.size or upload.size > MAX_DOCUMENT_BYTES:
        raise ValidationError("Documents must be non-empty and 10 MB or smaller.")
    extension = Path(upload.name).suffix.lower()
    if extension in {".png", ".jpg", ".jpeg", ".webp"}:
        validate_uploaded_image(upload)
    elif extension == ".pdf":
        try:
            upload.seek(0)
            header = upload.read(5)
            upload.seek(max(0, upload.size - 1024))
            tail = upload.read()
            if header != b"%PDF-" or b"%%EOF" not in tail:
                raise ValidationError("Upload a valid PDF document.")
        finally:
            upload.seek(0)
    else:
        raise ValidationError("Upload a PDF, JPEG, PNG, or WebP document.")
