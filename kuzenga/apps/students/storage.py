from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages
from django.utils.deconstruct import deconstructible


@deconstructible
class StudentDocumentStorage(FileSystemStorage):
    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return str(Path(self.base_location).resolve())

    def _open(self, name, mode):
        if "private_documents" in settings.STORAGES:
            return storages["private_documents"].open(name, mode)
        return super()._open(name, mode)

    def _save(self, name, content):
        if "private_documents" in settings.STORAGES:
            return storages["private_documents"].save(name, content)
        return super()._save(name, content)

    def exists(self, name):
        if "private_documents" in settings.STORAGES:
            return storages["private_documents"].exists(name)
        return super().exists(name)

    def delete(self, name):
        if "private_documents" in settings.STORAGES:
            return storages["private_documents"].delete(name)
        return super().delete(name)

    def size(self, name):
        if "private_documents" in settings.STORAGES:
            return storages["private_documents"].size(name)
        return super().size(name)

    def url(self, name):
        raise ValueError("Student documents require an authorized download route.")
