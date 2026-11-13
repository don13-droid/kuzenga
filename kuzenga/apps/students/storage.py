from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage, storages
from django.utils.deconstruct import deconstructible


@deconstructible
class StudentDocumentStorage(Storage):
    """Keep the historical migration import while selecting durable storage."""

    @property
    def backend(self):
        if "private_documents" in settings.STORAGES:
            return storages["private_documents"]
        return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return str(Path(self.base_location).resolve())

    def _open(self, name, mode="rb"):
        return self.backend.open(name, mode)

    def _save(self, name, content):
        return self.backend.save(name, content)

    def exists(self, name):
        return self.backend.exists(name)

    def delete(self, name):
        return self.backend.delete(name)

    def size(self, name):
        return self.backend.size(name)

    def path(self, name):
        return self.backend.path(name)

    def url(self, name):
        raise ValueError("Student documents require an authorized download route.")
