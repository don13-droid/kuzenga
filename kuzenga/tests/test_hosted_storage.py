import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import storages

from apps.students.storage import StudentDocumentStorage


def test_document_storage_delegates_without_exposing_a_url(settings, tmp_path):
    settings.STORAGES = {
        **settings.STORAGES,
        "private_documents": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path},
        },
    }
    storage = StudentDocumentStorage()
    name = storage.save("tenant-a/evidence.txt", ContentFile(b"preview fixture"))
    assert storages["private_documents"].exists(name)
    with storage.open(name) as document:
        assert document.read() == b"preview fixture"
    with pytest.raises(ValueError, match="authorized download route"):
        storage.url(name)
    storage.delete(name)
    assert not storage.exists(name)
