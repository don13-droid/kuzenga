"""Explicit, guarded migration rehearsal against an owner-selected preview DB."""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--env-file", help="Explicit ignored file containing staging environment values")
    parser.add_argument("--apply", action="store_true", help="Apply after reviewing the default plan")
    args = parser.parse_args()
    if args.env_file:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts.staging_preflight import load_environment

        load_environment(args.env_file)
    if os.environ.get("DEPLOYMENT_ENVIRONMENT") not in {"preview", "staging"} or os.environ.get("VERCEL_ENV") == "production":
        parser.error("Set DEPLOYMENT_ENVIRONMENT=preview or staging after verifying this is an isolated non-production target")
    direct_url = os.environ.get("DIRECT_DATABASE_URL", "")
    target = urlsplit(direct_url)
    if (
        target.scheme not in {"postgres", "postgresql"}
        or not target.hostname
        or target.hostname != args.expected_host
        or target.path != "/" + args.expected_database
        or "-pooler" in target.hostname
    ):
        parser.error("DIRECT_DATABASE_URL must match the expected direct PostgreSQL host and database")
    # Do not pass a connection URL on the command line or print environment values.
    os.environ["DATABASE_URL"] = direct_url
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.production"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import django
    from django.core.management import CommandError, call_command
    from django.db import connection

    django.setup()
    # Hold a session-level lock throughout inspection and migrations; never run
    # two initial schema rehearsals concurrently on the same target.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(728354106)")
        if not cursor.fetchone()[0]:
            raise CommandError("Another staging migration rehearsal holds the release lock")
    try:
        require_empty_database(connection)
        call_command("migrate", plan=not args.apply, interactive=False)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(728354106)")
        connection.close()


def require_empty_database(connection):
    from django.core.management import CommandError

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
            )
        """)
        if cursor.fetchone()[0]:
            raise CommandError("Refusing migrations: selected staging database is not empty")


if __name__ == "__main__":
    main()
