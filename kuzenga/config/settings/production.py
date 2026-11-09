from .base import *  # noqa: F403

DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not SECRET_KEY or SECRET_KEY == "dev-only-insecure-key" or SECRET_KEY.lower().startswith(  # noqa: F405
    ("replace-", "change-me", "your-secret")
):
    raise RuntimeError("Set a generated, non-placeholder DJANGO_SECRET_KEY in production")
if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("Set DJANGO_ALLOWED_HOSTS in production")
if "*" in ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("Wildcard DJANGO_ALLOWED_HOSTS is not allowed in production")
if DATABASES["default"]["ENGINE"] not in {  # noqa: F405
    "django.db.backends.postgresql",
    "django.db.backends.postgresql_psycopg2",
}:
    raise RuntimeError("Production requires PostgreSQL via DATABASE_URL")
