"""Offline production check and static build using synthetic inputs, never a live DB."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    # VERCEL=1 prevents reading local dotenv. Every relevant credential is synthetic.
    environment = {
        **os.environ,
        "VERCEL": "1",
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "DJANGO_ALLOWED_HOSTS": "preview.example.invalid",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://preview.example.invalid",
        # Exercise strict HSTS using only an isolated synthetic domain. Real domain
        # rollout must separately review these opt-ins and all its subdomains.
        "DJANGO_HSTS_INCLUDE_SUBDOMAINS": "True",
        "DJANGO_HSTS_PRELOAD": "True",
        "DATABASE_URL": "postgresql://offline:offline@127.0.0.1:1/offline?sslmode=require",
        "MEDIA_STORAGE_BACKEND": "s3",
        "DIRECT_UPLOADS_ENABLED": "True",
        "S3_ENDPOINT_URL": "https://objects.example.invalid",
        "S3_REGION_NAME": "us-east-1",
        "S3_BUCKET_NAME": "offline-private-bucket",
        "S3_ACCESS_KEY_ID": "offline-test-only",
        "S3_SECRET_ACCESS_KEY": "offline-test-only",
        "S3_ADDRESSING_STYLE": "auto",
    }
    code = """
import tempfile
from pathlib import Path
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
call_command('check', deploy=True, fail_level='WARNING')
with tempfile.TemporaryDirectory(prefix='kuzenga-static-') as directory:
    settings.STATIC_ROOT = Path(directory)
    call_command('collectstatic', interactive=False, verbosity=0)
    for name in ('css/tailwind.css', 'css/layout.css', 'admin/css/base.css'):
        if not (settings.STATIC_ROOT / name).is_file():
            raise RuntimeError('Missing collected asset: ' + name)
    for source in (settings.BASE_DIR / 'static').rglob('*'):
        if source.is_file():
            collected = settings.STATIC_ROOT / source.relative_to(settings.BASE_DIR / 'static')
            if collected.read_bytes() != source.read_bytes():
                raise RuntimeError('Collected asset differs from source')
print('Offline production checks and static collection passed; no database connected.')
"""
    subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, env=environment, check=True)


if __name__ == "__main__":
    main()
