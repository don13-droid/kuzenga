"""Read-only checks for an explicitly selected Vercel preview.

Run manually with the preview environment loaded. Does not migrate or write objects.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if os.environ.get("VERCEL_ENV") != "preview" or os.environ.get("KUZENGA_RESOURCE_ENV") != "preview":
        print("Refusing checks outside the selected preview environment.", file=sys.stderr)
        return 1
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

    import django

    django.setup()
    from botocore.exceptions import BotoCoreError, ClientError
    from django.conf import settings
    from django.core.files.storage import storages
    from django.db import DatabaseError, connection
    from django.db.migrations.executor import MigrationExecutor

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            print(f"Preview database has {len(pending)} pending migrations.", file=sys.stderr)
            return 1
        print("Preview Neon connectivity and migration consistency: passed")
    except DatabaseError:
        print("Preview database check failed; inspect credentials and connectivity securely.", file=sys.stderr)
        return 1
    finally:
        connection.close()

    if settings.MEDIA_STORAGE_BACKEND != "s3":
        print("Preview requires the existing private object storage.", file=sys.stderr)
        return 1
    try:
        storage = storages["default"]
        endpoint = storage.endpoint_url or ""
        if not endpoint.startswith("https://") or not endpoint.endswith(".r2.cloudflarestorage.com"):
            print("Preview storage is not the selected Cloudflare R2 endpoint.", file=sys.stderr)
            return 1
        storage.connection.meta.client.head_bucket(Bucket=storage.bucket_name)
        print("Preview Cloudflare R2 authenticated bucket access: passed (read-only)")
    except (BotoCoreError, ClientError):
        print("Preview storage check failed; inspect scoped credentials and connectivity securely.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
