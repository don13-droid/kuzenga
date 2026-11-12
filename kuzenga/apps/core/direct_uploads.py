"""Quarantined direct uploads; existing forms still validate and commit every file."""

import hashlib
import json
import re
import uuid
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.urls import Resolver404, resolve
from django.utils.deprecation import MiddlewareMixin
from django.views.decorators.http import require_POST

from apps.tenancy.models import Membership, Tenant
from apps.tenancy.permissions import has_permission
from apps.tenancy.services import has_module

from .validators import MAX_IMAGE_UPLOAD_BYTES, validate_uploaded_image

PREFIX = "_direct_upload_"
TTL = 300
MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".pdf": "application/pdf"}


def authorize(request, target, field):
    """Check destination and permission again at grant AND form consumption time."""
    if not request.user.is_authenticated or not request.user.is_active:
        raise PermissionDenied
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not target.startswith("/"):
        raise PermissionDenied
    try:
        match = resolve(target)
    except Resolver404 as exc:
        raise PermissionDenied from exc
    route, kwargs = match.view_name, match.kwargs
    tenant = getattr(request, "tenant", None)
    if route.startswith("superuser:"):
        if not request.user.is_superuser:
            raise PermissionDenied
        allowed = {
            "superuser:tenant-user-create": {"profile_image"},
            "superuser:tenant-user-edit": {"profile_image"},
            "superuser:tenant-configuration-section": {"logo"} if kwargs.get("section") == "identity" else set(),
        }
        if field not in allowed.get(route, set()):
            raise PermissionDenied
        school = Tenant.objects.filter(pk=kwargs.get("tenant_id")).first()
        if school is None:
            raise Http404
        if kwargs.get("membership_id") and not Membership.objects.filter(
            pk=kwargs["membership_id"], tenant=school
        ).exists():
            raise Http404
        return "image", str(school.pk)
    if tenant is None or request.user.is_superuser:
        raise PermissionDenied
    if route in {"students:create", "students:edit", "students:detail"}:
        from apps.students.models import Student

        if not has_module(tenant, "students") or not has_permission(request.membership, "students.manage"):
            raise PermissionDenied
        if kwargs.get("pk") and not Student.objects.filter(pk=kwargs["pk"]).exists():
            raise Http404
        expected = "file" if route == "students:detail" else "profile_image"
        if field == expected:
            return ("document" if field == "file" else "image"), str(tenant.pk)
    if route in {"admissions:create", "admissions:detail"} and field == "document-file":
        from apps.admissions.models import StudentApplication

        if not has_module(tenant, "students") or not has_permission(request.membership, "admissions.manage"):
            raise PermissionDenied
        if kwargs.get("pk") and not StudentApplication.objects.filter(pk=kwargs["pk"]).exists():
            raise Http404
        return "document", str(tenant.pk)
    if route in {"tenancy:user-create", "tenancy:user-edit"} and field == "profile_image":
        if not has_permission(request.membership, "users.manage"):
            raise PermissionDenied
        if kwargs.get("membership_id") and not Membership.objects.filter(
            pk=kwargs["membership_id"], tenant=tenant
        ).exists():
            raise Http404
        return "image", str(tenant.pk)
    raise PermissionDenied


def client():
    return storages["private_documents"].connection.meta.client


def salt(request):
    return "core.direct-upload:" + (request.session.session_key or "")


@login_required
@require_POST
def grant(request):
    if not settings.DIRECT_UPLOADS_ENABLED:
        raise Http404
    if len(request.body) > 4096:
        return HttpResponseBadRequest("Invalid upload request.")
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        target, field = data["target"], data["field"]
        if not isinstance(target, str) or not isinstance(field, str):
            raise ValueError
        kind, scope = authorize(request, target, field)
        name, size, digest = data["name"], data["size"], data["sha256"]
        if not isinstance(name, str) or PurePosixPath(name).name != name or "\\" in name or len(name) > 200:
            raise ValueError
        mime = MIME_TYPES.get(PurePosixPath(name).suffix.lower())
        limit = MAX_IMAGE_UPLOAD_BYTES if kind == "image" or mime != "application/pdf" else 10 * 1024 * 1024
        if mime is None or (kind == "image" and mime == "application/pdf"):
            raise ValueError
        if type(size) is not int or not 0 < size <= limit or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest("Invalid upload request.")
    key = f"staging-uploads/{scope}/{uuid.uuid4().hex}"
    payload = {"key": key, "scope": scope, "kind": kind, "name": name, "size": size, "sha256": digest,
               "target": target, "field": field, "user": str(request.user.pk), "mime": mime}
    try:
        url = client().generate_presigned_url(
            "put_object", Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key, "ContentType": mime,
                                  "ContentLength": size}, ExpiresIn=TTL, HttpMethod="PUT",
        )
    except (BotoCoreError, ClientError):
        return JsonResponse({"error": "Upload storage is unavailable. Please retry."}, status=503)
    response = JsonResponse({"url": url, "ticket": signing.dumps(payload, salt=salt(request)), "content_type": mime})
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


class DirectUploadMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        # This hook runs after CSRF verification, inside existing tenant context.
        if request.method != "POST" or not settings.DIRECT_UPLOADS_ENABLED:
            return None
        tickets = [(key[len(PREFIX):], request.POST.getlist(key)) for key in request.POST if key.startswith(PREFIX)]
        if not tickets:
            return None
        if len(tickets) > 3:
            return HttpResponseBadRequest("Too many uploads.")
        files = request.FILES.copy()
        try:
            for field, values in tickets:
                if len(values) != 1 or field in files:
                    raise ValueError
                payload = signing.loads(values[0], salt=salt(request), max_age=TTL)
                kind, scope = authorize(request, request.path, field)
                if (payload["user"] != str(request.user.pk) or payload["scope"] != scope
                        or payload["target"] != request.path or payload["field"] != field or payload["kind"] != kind):
                    raise PermissionDenied
                # A grant cannot be swapped onto another action on a multi-form page.
                if field in {"file", "document-file"} and resolve(request.path).view_name.endswith(":detail"):
                    if request.POST.get("action") != "document":
                        raise PermissionDenied
                result = client().get_object(Bucket=settings.S3_BUCKET_NAME, Key=payload["key"])
                body = result["Body"]
                try:
                    if result["ContentLength"] != payload["size"]:
                        raise ValueError
                    content = body.read(payload["size"] + 1)
                finally:
                    body.close()
                if len(content) != payload["size"] or hashlib.sha256(content).hexdigest() != payload["sha256"]:
                    raise ValueError
                upload = SimpleUploadedFile(payload["name"], content, content_type=payload["mime"])
                if kind == "image":
                    validate_uploaded_image(upload)
                else:
                    from apps.students.validators import validate_student_document

                    validate_student_document(upload)
                files[field] = upload
        except (signing.BadSignature, KeyError, TypeError, ValueError, ValidationError):
            return HttpResponseBadRequest("Upload expired or failed validation. Please select the file again.")
        except (BotoCoreError, ClientError):
            return JsonResponse({"error": "Upload storage is unavailable. Please retry."}, status=503)
        request._files = files
        return None
