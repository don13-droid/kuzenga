"""Probe selected staging resources without migrations, deletion or secret output."""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import Request, urlopen

import boto3
import environ
import psycopg
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.core.management import CommandError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_environment(path):
    """Read only an explicitly supplied, untracked environment file."""
    import subprocess

    selected = Path(path).resolve()
    repository = PROJECT_ROOT.parent
    if selected.is_relative_to(repository):
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", str(selected)], cwd=repository, capture_output=True, check=False,
        )
        if result.returncode != 0:
            raise ValueError("Environment input inside the repository must be Git-ignored")
    # django-environ logs malformed lines verbatim. Validate first and pass only
    # valid assignments, so a malformed credential can never enter the logs.
    assignments = []
    for line in selected.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not re.fullmatch(r"(?:export )?[A-Za-z_][A-Za-z0-9_]*=.*", line):
            raise ValueError("Environment input must contain single-line NAME=value assignments")
        assignments.append(line)
    environ.Env.read_env(io.StringIO("\n".join(assignments)), overwrite=False)


def verify_database(url, expected_host, expected_database, *, pooled=False):
    target = urlsplit(url)
    host = target.hostname or ""
    if pooled:
        host = host.replace("-pooler.", ".", 1)
    options = parse_qs(target.query)
    sslmode = options.get("sslmode", ["require"])[0]
    if (
        target.scheme not in {"postgres", "postgresql"} or host != expected_host
        or unquote(target.path) != "/" + expected_database
        or sslmode not in {"require", "verify-ca", "verify-full"}
        or (not pooled and "-pooler." in host)
    ):
        raise ValueError("Database URL must match the selected staging target and require TLS")
    with psycopg.connect(url, sslmode=sslmode, connect_timeout=10, autocommit=True) as connection:
        if not connection.pgconn.ssl_in_use:
            raise ValueError("Database transport is not encrypted")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != expected_database:
                raise ValueError("Connected database does not match the selected staging target")
        if not pooled:
            from scripts.migrate_preview import require_empty_database

            require_empty_database(connection)


def verify_r2(origin, expected_bucket):
    endpoint = os.environ["S3_ENDPOINT_URL"]
    bucket = os.environ["S3_BUCKET_NAME"]
    if bucket != expected_bucket:
        raise ValueError("R2 bucket must match the explicitly selected private staging bucket")
    host = urlsplit(endpoint).hostname or ""
    if urlsplit(endpoint).scheme != "https" or not host.endswith(".r2.cloudflarestorage.com"):
        raise ValueError("Select the private Cloudflare R2 S3 endpoint")
    sdk = boto3.client(
        "s3", endpoint_url=endpoint, region_name="auto",
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=30, retries={"max_attempts": 1}),
    )
    # Synthetic PDF exceeds Vercel's 4.5 MB request limit. Never use school data.
    content = b"%PDF-1.4\n" + b" " * (5 * 1024 * 1024) + b"\n%%EOF"
    key = "staging-validation/" + uuid.uuid4().hex + ".pdf"
    params = {"Bucket": bucket, "Key": key, "ContentType": "application/pdf", "ContentLength": len(content)}
    url = sdk.generate_presigned_url("put_object", Params=params, ExpiresIn=120, HttpMethod="PUT")
    with urlopen(Request(url, data=content, method="PUT", headers={"Content-Type": "application/pdf"}), timeout=30) as response:
        if response.status != 200:
            raise ValueError("R2 presigned PUT did not succeed")
    print(json.dumps({"synthetic_object_retained": key}))
    result = sdk.get_object(Bucket=bucket, Key=key)
    body = result["Body"]
    try:
        received = body.read(len(content) + 1)
    finally:
        body.close()
    if len(received) != len(content) or hashlib.sha256(received).digest() != hashlib.sha256(content).digest():
        raise ValueError("R2 download did not match the synthetic upload")
    try:
        with urlopen(f"{endpoint.rstrip('/')}/{bucket}/{key}", timeout=15):
            raise ValueError("R2 S3 object unexpectedly permits anonymous access")
    except HTTPError as exc:
        if exc.code != 403:
            raise ValueError("Could not establish anonymous-access denial") from None
    # A bucket-scoped object token may not permit this read. Report rather than
    # modifying CORS or overstating browser access verification.
    cors = sdk.get_bucket_cors(Bucket=bucket)["CORSRules"]
    if any("*" in rule.get("AllowedOrigins", []) for rule in cors) or not any(
        rule.get("AllowedOrigins") == [origin] and "PUT" in rule.get("AllowedMethods", [])
        and any(header.lower() in {"content-type", "*"} for header in rule.get("AllowedHeaders", []))
        for rule in cors
    ):
        raise ValueError("Bucket CORS must allow the exact selected staging origin and PUT Content-Type")
    print(json.dumps({"r2_upload_download": "passed", "anonymous_s3_get": "denied", "cors": "matched",
                      "synthetic_object_retained": key}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--r2", action="store_true")
    parser.add_argument("--expected-host")
    parser.add_argument("--expected-database")
    parser.add_argument("--allowed-origin")
    parser.add_argument("--expected-bucket")
    args = parser.parse_args()
    try:
        if args.env_file:
            load_environment(args.env_file)
        if os.environ.get("DEPLOYMENT_ENVIRONMENT") not in {"staging", "preview"} or os.environ.get("VERCEL_ENV") == "production":
            raise ValueError("Explicit staging/preview selection is required; production is refused")
        if not args.database and not args.r2:
            raise ValueError("Choose --database and/or --r2")
        if args.database:
            if not args.expected_host or not args.expected_database:
                raise ValueError("Provide the selected expected staging host and database")
            verify_database(os.environ["DIRECT_DATABASE_URL"], args.expected_host, args.expected_database)
            verify_database(os.environ["DATABASE_URL"], args.expected_host, args.expected_database, pooled=True)
            print("Neon direct/pooled TLS connectivity passed; selected staging database is empty.")
        if args.r2:
            if not args.allowed_origin or not args.expected_bucket:
                raise ValueError("Provide the selected private staging bucket and exact origin for CORS verification")
            verify_r2(args.allowed_origin, args.expected_bucket)
    except (KeyError, ValueError) as exc:
        # Only these deliberately authored validation messages are safe to print.
        message = "A required staging environment variable is missing" if isinstance(exc, KeyError) else str(exc)
        parser.error(message)
    except (psycopg.Error, BotoCoreError, ClientError, URLError):
        # Never print provider exceptions: they can contain signed URLs or credentials.
        print("Staging service validation failed. Check credentials, permissions and connectivity securely.", file=sys.stderr)
        return 1
    except CommandError:
        print("Refusing database validation: selected staging database is not empty.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT))
    raise SystemExit(main())
