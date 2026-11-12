"""Check or apply migrations using a direct, independently identified Preview endpoint."""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the reviewed Preview migration plan.")
    args = parser.parse_args()
    if os.environ.get("KUZENGA_RESOURCE_ENV") != "preview":
        parser.error("KUZENGA_RESOURCE_ENV must be preview")

    direct_url = os.environ.get("DATABASE_URL_UNPOOLED", "")
    direct = urlsplit(direct_url)
    pooled = urlsplit(os.environ.get("DATABASE_URL", ""))
    expected_host = os.environ.get("KUZENGA_PREVIEW_DIRECT_HOST")
    if (
        direct.scheme not in {"postgres", "postgresql"}
        or not expected_host
        or direct.hostname != expected_host
        or "-pooler." in expected_host
        or "." not in expected_host
        or pooled.hostname != expected_host.replace(".", "-pooler.", 1)
        or direct.path != pooled.path
        or parse_qs(direct.query).get("sslmode") != ["require"]
    ):
        parser.error("Direct and pooled URLs must match the verified Preview branch and database, with SSL required")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ["DATABASE_URL"] = direct_url
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.production"

    import django
    from django.core.management import call_command

    django.setup()
    call_command("makemigrations", check=True, dry_run=True)
    call_command("migrate", plan=True)
    if args.apply:
        call_command("migrate", interactive=False)
        call_command("migrate", check=True)


if __name__ == "__main__":
    main()
