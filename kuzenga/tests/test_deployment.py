import json
import os
import runpy
import secrets
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from botocore.stub import Stubber
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.urls import reverse

from apps.core.context import tenant_context
from apps.core.storage import ProtectedImageStorage
from apps.students.models import StudentDocument
from apps.students.storage import StudentDocumentStorage

from .test_student_management import detail, make_student, pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("vercel,expected", [("1", "production"), ("0", "development")])
def test_native_discovery_defaults_to_production_only_on_vercel(monkeypatch, vercel, expected):
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.setenv("VERCEL", vercel)
    with patch("django.core.management.execute_from_command_line") as execute:
        runpy.run_path(str(PROJECT_ROOT / "manage.py"), run_name="__main__")
    execute.assert_called_once()
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings." + expected


def production_environment(**changes):
    return {
        **os.environ,
        "VERCEL": "1",
        "VERCEL_URL": "",
        "VERCEL_BRANCH_URL": "",
        "VERCEL_PROJECT_PRODUCTION_URL": "",
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "DJANGO_ALLOWED_HOSTS": "preview.example.invalid",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://preview.example.invalid",
        "DATABASE_URL": "postgresql://offline:offline@127.0.0.1:1/offline?sslmode=require&channel_binding=require",
        "MEDIA_STORAGE_BACKEND": "s3",
        "DIRECT_UPLOADS_ENABLED": "True",
        "S3_ENDPOINT_URL": "https://objects.example.invalid",
        "S3_REGION_NAME": "us-east-1",
        "S3_BUCKET_NAME": "offline-private",
        "S3_ACCESS_KEY_ID": "offline-test-only",
        "S3_SECRET_ACCESS_KEY": "offline-test-only",
        **changes,
    }


@pytest.mark.parametrize("changes,message", [
    ({"DATABASE_URL": "sqlite:///:memory:"}, "requires PostgreSQL"),
    ({"DATABASE_URL": "postgresql://offline@localhost/offline?sslmode=disable"}, "requires TLS"),
    ({"DATABASE_URL": "postgresql://offline@localhost/offline?sslmode=prefer"}, "requires TLS"),
    ({"DJANGO_SECRET_KEY": "replace-with-secret"}, "non-placeholder"),
    ({"DJANGO_SECRET_KEY": "short-key"}, "non-placeholder"),
    ({"DJANGO_ALLOWED_HOSTS": "*"}, "explicit hostnames"),
    ({"DJANGO_ALLOWED_HOSTS": ".vercel.app"}, "explicit hostnames"),
    ({"DJANGO_CSRF_TRUSTED_ORIGINS": "http://preview.example.invalid"}, "exact HTTPS"),
    ({"DJANGO_CSRF_TRUSTED_ORIGINS": "https://other.example.invalid"}, "exact HTTPS"),
    ({"MEDIA_STORAGE_BACKEND": "filesystem"}, "external media storage"),
    ({"DIRECT_UPLOADS_ENABLED": "False"}, "requires validated direct uploads"),
    ({"S3_ENDPOINT_URL": "http://objects.example.invalid"}, "must use HTTPS"),
    ({"S3_SECRET_ACCESS_KEY": ""}, "bucket, region and access credentials"),
])
def test_production_rejects_unsafe_configuration(changes, message):
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.production"],
        cwd=PROJECT_ROOT, env=production_environment(**changes), capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert message in result.stderr


def test_production_neon_configuration_and_security_defaults():
    code = """
import json
from config.settings import production as s
db = s.DATABASES['default']
print(json.dumps({
    'age': db['CONN_MAX_AGE'], 'cursors': db['DISABLE_SERVER_SIDE_CURSORS'],
    'ssl': db['OPTIONS']['sslmode'], 'binding': db['OPTIONS']['channel_binding'],
    'session': s.SESSION_ENGINE, 'secure': s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE,
    'debug': s.DEBUG, 'static': s.STORAGES['staticfiles']['BACKEND'],
    'documents': s.STORAGES['private_documents']['BACKEND'],
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PROJECT_ROOT, env=production_environment(),
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == {
        "age": 0, "cursors": True, "ssl": "require", "binding": "require",
        "session": "django.contrib.sessions.backends.db", "secure": True, "debug": False,
        "static": "django.contrib.staticfiles.storage.StaticFilesStorage",
        "documents": "storages.backends.s3.S3Storage",
    }



def test_vercel_only_allows_its_exact_deployment_and_branch_hosts():
    code = """
import json
from django.http.request import validate_host
from config.settings.production import ALLOWED_HOSTS
print(json.dumps({
    'hosts': ALLOWED_HOSTS,
    'deployment': validate_host('kuzenga-own.vercel.app', ALLOWED_HOSTS),
    'branch': validate_host('kuzenga-git-fix-own.vercel.app', ALLOWED_HOSTS),
    'unrelated': validate_host('unrelated.vercel.app', ALLOWED_HOSTS),
    'production': validate_host('production-only.vercel.app', ALLOWED_HOSTS),
    'child': validate_host('child.kuzenga-own.vercel.app', ALLOWED_HOSTS),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PROJECT_ROOT,
        env=production_environment(
            VERCEL_URL="kuzenga-own.vercel.app",
            VERCEL_BRANCH_URL="kuzenga-git-fix-own.vercel.app",
            VERCEL_PROJECT_PRODUCTION_URL="production-only.vercel.app",
        ),
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == {
        "hosts": ["preview.example.invalid", "kuzenga-own.vercel.app", "kuzenga-git-fix-own.vercel.app"],
        "deployment": True, "branch": True, "unrelated": False, "production": False, "child": False,
    }


@pytest.mark.parametrize("variable", ["VERCEL_URL", "VERCEL_BRANCH_URL"])
@pytest.mark.parametrize("hostname", [
    "https://kuzenga.vercel.app", "//kuzenga.vercel.app", "kuzenga.vercel.app/path",
    "kuzenga.vercel.app:443", "user@kuzenga.vercel.app", "kuzenga.vercel.app\n",
    "Kuzenga.vercel.app", "-kuzenga.vercel.app", "kuzenga-.vercel.app",
    "kuzenga..vercel.app", "kuzenga.vercel.app.evil.invalid", "*.vercel.app",
    "vercel.app", "a" * 64 + ".vercel.app",
])
def test_vercel_rejects_malformed_system_hostnames(variable, hostname):
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.production"], cwd=PROJECT_ROOT,
        env=production_environment(**{variable: hostname}), capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert variable + " must be an exact lowercase Vercel DNS hostname" in result.stderr


def test_vercel_still_requires_explicit_configured_hosts():
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.production"], cwd=PROJECT_ROOT,
        env=production_environment(DJANGO_ALLOWED_HOSTS="", VERCEL_URL="kuzenga-own.vercel.app"),
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Set DJANGO_ALLOWED_HOSTS in production" in result.stderr


def test_vercel_system_hosts_are_ignored_outside_vercel():
    result = subprocess.run(
        [sys.executable, "-c", "import json; from config.settings.production import ALLOWED_HOSTS; print(json.dumps(ALLOWED_HOSTS))"],
        cwd=PROJECT_ROOT,
        env=production_environment(VERCEL="0", VERCEL_URL="https://untrusted.invalid/path", VERCEL_BRANCH_URL="wrong:443"),
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == ["preview.example.invalid"]


def test_object_image_urls_keep_authorized_django_route():
    storage = ProtectedImageStorage(bucket_name="offline-private")
    assert storage.url("tenant-logos/school name.png") == "/media/tenant-logos/school%20name.png"


def test_missing_s3_object_is_a_file_not_found_without_a_live_bucket():
    storage = ProtectedImageStorage(
        bucket_name="offline-private", access_key="offline-test-only", secret_key="offline-test-only",
        region_name="us-east-1", endpoint_url="https://objects.example.invalid",
    )
    with Stubber(storage.connection.meta.client) as stubber:
        stubber.add_client_error("head_object", service_error_code="404", http_status_code=404)
        with pytest.raises(FileNotFoundError):
            storage.open("tenant-logos/missing.png")
        stubber.assert_no_pending_responses()


def test_private_documents_use_configured_alias_without_public_url(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "private_documents": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }
    storage = StudentDocumentStorage()
    name = storage.save("documents/record.pdf", ContentFile(b"private"))
    assert storages["private_documents"].exists(name)
    with storage.open(name) as stream:
        assert stream.read() == b"private"
    with pytest.raises(ValueError, match="authorized download"):
        storage.url(name)
    assert storage.deconstruct()[0] == "apps.students.storage.StudentDocumentStorage"


def test_remote_document_download_retains_tenant_authorization(client, settings, tenant_a, admin_a, admin_b, teacher_a):
    settings.STORAGES = {
        **settings.STORAGES,
        "private_documents": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }
    student = make_student(tenant_a)
    client.force_login(admin_a)
    assert client.post(detail(student), {"action": "document", "title": "Record", "file": pdf()}).status_code == 302
    with tenant_context(tenant_a):
        document = StudentDocument.objects.get(student=student)
    url = reverse("students:document-download", args=[student.pk, document.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert b"".join(response.streaming_content).startswith(b"%PDF-")
    client.force_login(admin_b)
    assert client.get(url).status_code == 404
    client.force_login(teacher_a)
    assert client.get(url).status_code == 403
    client.logout()
    assert client.get(url).status_code == 302


def test_preview_migration_tool_refuses_unselected_target():
    environment = {**os.environ, "DEPLOYMENT_ENVIRONMENT": "production"}
    result = subprocess.run(
        [sys.executable, "scripts/migrate_preview.py", "--expected-host", "localhost", "--expected-database", "test"],
        cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "isolated non-production" in result.stderr


@pytest.mark.parametrize("url", [
    "", "sqlite:///:memory:",
    "postgresql://offline@other.example.invalid/preview",
    "postgresql://offline@direct.example.invalid/production",
    "postgresql://offline@direct-pooler.example.invalid/preview",
])
def test_preview_migration_tool_rejects_wrong_or_pooled_target(url):
    environment = {**os.environ, "DEPLOYMENT_ENVIRONMENT": "preview", "DIRECT_DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "scripts/migrate_preview.py", "--expected-host", "direct.example.invalid",
         "--expected-database", "preview"],
        cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "must match the expected direct PostgreSQL" in result.stderr
