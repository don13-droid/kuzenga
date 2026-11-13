"""Explicit operator command: allow PUT only from the stable preview origin."""
import os
from urllib.parse import urlsplit
assert os.environ["VERCEL_ENV"] == "preview"
assert os.environ["KUZENGA_RESOURCE_ENV"] == "preview"
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings.production")
import django
django.setup()
from django.conf import settings
from apps.core.direct_uploads import client
from botocore.exceptions import ClientError
assert settings.S3_BUCKET_NAME == "kuzenga-preview"
s3=client()
assert urlsplit(s3.meta.endpoint_url).hostname == "0843467c10417a1fe60583561f907b1b.r2.cloudflarestorage.com"
try:
    rules=s3.get_bucket_cors(Bucket=settings.S3_BUCKET_NAME)["CORSRules"]
except ClientError as error:
    if error.response.get("Error",{}).get("Code") != "NoSuchCORSConfiguration":
        print("Existing R2 credentials cannot inspect preview CORS; no change made.")
        raise SystemExit(1)
    rules=[]
desired={"AllowedOrigins":["https://kuzenga-preview-donewells-projects.vercel.app"],"AllowedMethods":["PUT"],"AllowedHeaders":["content-type"],"MaxAgeSeconds":3600}
if desired not in rules:
    try:
        s3.put_bucket_cors(Bucket=settings.S3_BUCKET_NAME,CORSConfiguration={"CORSRules":[*rules,desired]})
    except ClientError:
        print("Existing R2 credentials cannot configure preview CORS; no broader credentials requested.")
        raise SystemExit(1)
print("Exact stable-preview PUT CORS configured; existing rules preserved.")
