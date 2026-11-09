from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
SECRET_KEY = "test-key"
DATABASES = {"default": env.db_url("DATABASE_URL", default="sqlite:///:memory:")}  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
