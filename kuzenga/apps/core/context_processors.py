from django.conf import settings


def uploads(request):
    return {"direct_uploads_enabled": settings.DIRECT_UPLOADS_ENABLED}
