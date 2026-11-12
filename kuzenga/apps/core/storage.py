"""Private object storage that retains the existing authorized image route."""

from urllib.parse import quote

from storages.backends.s3 import S3Storage


class ProtectedImageStorage(S3Storage):
    def url(self, name, parameters=None, expire=None, http_method=None):
        # Never hand the browser a bucket URL that bypasses record authorization.
        return "/media/" + quote(name, safe="/")
