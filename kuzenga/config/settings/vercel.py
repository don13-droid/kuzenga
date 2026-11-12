"""Hosted settings shared by Preview and a separately approved production release."""

from urllib.parse import urlsplit

from .production import *  # noqa: F403

vercel_environment = env("VERCEL_ENV", default="")  # noqa: F405
if vercel_environment not in {"preview", "production"}:
    raise RuntimeError("VERCEL_ENV must be preview or production")
if env("KUZENGA_RESOURCE_ENV") != vercel_environment:  # noqa: F405
    raise RuntimeError("Hosted resource scope must match VERCEL_ENV")

database = DATABASES["default"]  # noqa: F405
database_host = database["HOST"]
if "-pooler." not in database_host or database_host != env("KUZENGA_POOLED_DATABASE_HOST"):  # noqa: F405
    raise RuntimeError("DATABASE_URL must use the configured pooled Neon endpoint")
database["CONN_MAX_AGE"] = 0
database["DISABLE_SERVER_SIDE_CURSORS"] = True
database.setdefault("OPTIONS", {}).update(sslmode="require", prepare_threshold=None)

if any(host.startswith(".") for host in ALLOWED_HOSTS):  # noqa: F405
    raise RuntimeError("Hosted deployments require exact allowed hostnames")

deployment_host = env("VERCEL_URL", default="")  # noqa: F405
if vercel_environment == "preview" and deployment_host.endswith(".vercel.app"):
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, deployment_host]  # noqa: F405

CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405
SECURE_HSTS_SECONDS = 0 if vercel_environment == "preview" else SECURE_HSTS_SECONDS  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = vercel_environment == "production"
SECURE_HSTS_PRELOAD = False

endpoint = env("KUZENGA_STORAGE_ENDPOINT")  # noqa: F405
if urlsplit(endpoint).scheme != "https" or not urlsplit(endpoint).hostname:
    raise RuntimeError("KUZENGA_STORAGE_ENDPOINT must be an HTTPS S3 endpoint")
bucket = env("KUZENGA_STORAGE_BUCKET")  # noqa: F405
if not bucket.endswith(f"-{vercel_environment}"):
    raise RuntimeError("The private storage bucket name must end with its environment")
storage_options = {
    "endpoint_url": endpoint,
    "bucket_name": bucket,
    "access_key": env("KUZENGA_STORAGE_ACCESS_KEY_ID"),  # noqa: F405
    "secret_key": env("KUZENGA_STORAGE_SECRET_ACCESS_KEY"),  # noqa: F405
    "region_name": env("KUZENGA_STORAGE_REGION", default="auto"),  # noqa: F405
    "addressing_style": "path",
    "default_acl": None,
    "file_overwrite": False,
    "object_parameters": {"CacheControl": "private, no-store"},
}
STORAGES = {
    "default": {
        "BACKEND": "apps.core.storage.ProtectedImageStorage",
        "OPTIONS": {**storage_options, "location": "images"},
    },
    "private_documents": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {**storage_options, "location": "documents"},
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}
