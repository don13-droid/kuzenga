import warnings
from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_FORMAT_EXTENSIONS = {
    "JPEG": {".jpg", ".jpeg"},
    "PNG": {".png"},
    "WEBP": {".webp"},
}


def validate_uploaded_image(upload):
    if upload.size > MAX_IMAGE_UPLOAD_BYTES:
        raise ValidationError("Images must be 5 MB or smaller.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(upload)
            image_format = image.format
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValidationError("Image dimensions must be 20 megapixels or smaller.")
            image.verify()
    except ValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
    ) as exc:
        raise ValidationError("Upload a valid JPEG, PNG, or WebP image.") from exc
    finally:
        upload.seek(0)

    extension = Path(upload.name).suffix.lower()
    if extension not in IMAGE_FORMAT_EXTENSIONS.get(image_format, set()):
        raise ValidationError("Image file extension must match its JPEG, PNG, or WebP format.")
