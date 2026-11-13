"""Explicit operator command: allow PUT only from the stable preview origin."""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if os.environ.get("VERCEL_ENV") != "preview" or os.environ.get("KUZENGA_RESOURCE_ENV") != "preview":
        print("Refusing CORS configuration outside the selected preview.")
        return 1
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
    import django

    django.setup()
    from botocore.exceptions import BotoCoreError, ClientError
    from django.conf import settings

    from apps.core.direct_uploads import client

    s3 = client()
    if (
        settings.S3_BUCKET_NAME != "kuzenga-preview"
        or urlsplit(s3.meta.endpoint_url).hostname
        != "0843467c10417a1fe60583561f907b1b.r2.cloudflarestorage.com"
    ):
        print("Refusing CORS configuration for an unselected bucket or endpoint.")
        return 1
    try:
        try:
            rules = s3.get_bucket_cors(Bucket=settings.S3_BUCKET_NAME)["CORSRules"]
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "NoSuchCORSConfiguration":
                print("Existing R2 credentials cannot inspect preview CORS; no change made.")
                return 1
            rules = []
        desired = {
            "AllowedOrigins": ["https://kuzenga-preview-donewells-projects.vercel.app"],
            "AllowedMethods": ["PUT"], "AllowedHeaders": ["content-type"], "MaxAgeSeconds": 3600,
        }
        if desired not in rules:
            s3.put_bucket_cors(Bucket=settings.S3_BUCKET_NAME, CORSConfiguration={"CORSRules": [*rules, desired]})
    except (BotoCoreError, ClientError):
        print("Preview CORS operation failed; review existing scoped permissions securely.")
        return 1
    print("Exact stable-preview PUT CORS configured; existing rules preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
