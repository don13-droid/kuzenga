import re
from urllib.parse import urlsplit

from .base import *  # noqa: F403

DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
# Do not impose HSTS on unrelated services sharing the registered domain.
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", default=False)  # noqa: F405
SECURE_HSTS_PRELOAD = env.bool("DJANGO_HSTS_PRELOAD", default=False)  # noqa: F405
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.lower().startswith(  # noqa: F405
    ("replace-", "change-me", "your-secret")
):
    raise RuntimeError("Set a generated, non-placeholder DJANGO_SECRET_KEY of at least 50 characters in production")
if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("Set DJANGO_ALLOWED_HOSTS in production")
if any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host) for host in ALLOWED_HOSTS):  # noqa: F405
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must contain explicit hostnames without wildcards, ports or schemes")
# Vercel supplies these exact deployment/branch DNS names; never infer trust from
# request headers or grant access to every vercel.app deployment.
if env.bool("VERCEL", default=False):  # noqa: F405
    ALLOWED_HOSTS = list(ALLOWED_HOSTS)  # noqa: F405
    for variable_name in ("VERCEL_URL", "VERCEL_BRANCH_URL"):
        vercel_hostname = env(variable_name, default="")  # noqa: F405
        if not vercel_hostname:
            continue
        if (
            len(vercel_hostname) > 253
            or not vercel_hostname.endswith(".vercel.app")
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in vercel_hostname.split(".")
            )
        ):
            raise RuntimeError(f"{variable_name} must be an exact lowercase Vercel DNS hostname")
        if vercel_hostname not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(vercel_hostname)

CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405
for origin in CSRF_TRUSTED_ORIGINS:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in ALLOWED_HOSTS  # noqa: F405
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("CSRF trusted origins must be exact HTTPS origins matching DJANGO_ALLOWED_HOSTS")
if DATABASES["default"]["ENGINE"] not in {  # noqa: F405
    "django.db.backends.postgresql",
    "django.db.backends.postgresql_psycopg2",
}:
    raise RuntimeError("Production requires PostgreSQL via DATABASE_URL")

# Neon transaction pooling: no process-local persistent pool or named cursors.
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True  # noqa: F405
database_options = DATABASES["default"].setdefault("OPTIONS", {})  # noqa: F405
database_options.setdefault("sslmode", "require")
database_options.setdefault("connect_timeout", 10)
if database_options["sslmode"] not in {"require", "verify-ca", "verify-full"}:
    raise RuntimeError("Production PostgreSQL requires TLS (sslmode=require or verify-*)")

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Provider-neutral S3-compatible storage; no resource is created by configuration.
MEDIA_STORAGE_BACKEND = env("MEDIA_STORAGE_BACKEND", default="filesystem")  # noqa: F405
if MEDIA_STORAGE_BACKEND not in {"filesystem", "s3"}:
    raise RuntimeError("MEDIA_STORAGE_BACKEND must be filesystem or s3")
if env.bool("VERCEL", default=False) and MEDIA_STORAGE_BACKEND != "s3":  # noqa: F405
    raise RuntimeError("Vercel requires external media storage: set MEDIA_STORAGE_BACKEND=s3")
if env.bool("VERCEL", default=False) and not DIRECT_UPLOADS_ENABLED:  # noqa: F405
    raise RuntimeError("Vercel requires validated direct uploads: set DIRECT_UPLOADS_ENABLED=True after staging checks")
if DIRECT_UPLOADS_ENABLED and MEDIA_STORAGE_BACKEND != "s3":  # noqa: F405
    raise RuntimeError("Direct uploads require private S3-compatible storage")
if MEDIA_STORAGE_BACKEND == "s3":
    endpoint = env("S3_ENDPOINT_URL", default="")  # noqa: F405
    if endpoint and (urlsplit(endpoint).scheme != "https" or not urlsplit(endpoint).hostname):
        raise RuntimeError("S3_ENDPOINT_URL must use HTTPS")
    bucket = env("S3_BUCKET_NAME", default="")  # noqa: F405
    region = env("S3_REGION_NAME", default="")  # noqa: F405
    access_key = env("S3_ACCESS_KEY_ID", default="")  # noqa: F405
    secret_key = env("S3_SECRET_ACCESS_KEY", default="")  # noqa: F405
    if not all((bucket, region, access_key, secret_key)):
        raise RuntimeError("S3 media requires bucket, region and access credentials in the environment store")
    S3_BUCKET_NAME = bucket
    s3_options = {
        "bucket_name": bucket,
        "region_name": region,
        "access_key": access_key,
        "secret_key": secret_key,
        "endpoint_url": endpoint or None,
        "addressing_style": env("S3_ADDRESSING_STYLE", default="auto"),  # noqa: F405
        "default_acl": None,
        "file_overwrite": False,
        "custom_domain": None,
        "querystring_auth": True,
        "signature_version": "s3v4",
        "use_ssl": True,
        "verify": True,
        "object_parameters": {"CacheControl": "private, no-store"},
    }
    STORAGES = {
        "default": {"BACKEND": "apps.core.storage.ProtectedImageStorage", "OPTIONS": s3_options},
        "private_documents": {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": s3_options},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
