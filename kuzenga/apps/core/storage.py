from django.urls import reverse
from storages.backends.s3 import S3Storage


class ProtectedImageStorage(S3Storage):
    """Keep image URLs behind the existing record-level authorization view."""

    def url(self, name):
        return reverse("protected-image", kwargs={"path": name})
