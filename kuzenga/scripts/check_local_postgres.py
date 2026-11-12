"""Create a new local-only PostgreSQL sandbox, migrate and test; retain all data."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

import psycopg
from psycopg import sql

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT.parent / ".deployment-tools"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finance-only", action="store_true", help="Run finance tests, including opt-in concurrency acceptance")
    args = parser.parse_args()
    if os.environ.get("VERCEL_ENV") == "production":
        raise RuntimeError("Local validation is refused in a production environment")
    pg_bin = TOOLS / "pgsql16" / "pgsql" / "bin"
    if not (pg_bin / "postgres.exe").exists():
        destination = TOOLS / "pgsql16"
        destination.mkdir(exist_ok=True)
        with zipfile.ZipFile(TOOLS / "postgresql-16.15.zip") as archive:
            for member in archive.infolist():
                name = member.filename.replace("\\", "/")
                if not name.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/")):
                    continue
                target = (destination / name).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError("Archive member would escape the isolated tools directory")
                archive.extract(member, destination)
    openssl = Path("C:/Program Files/Git/usr/bin/openssl.exe")
    if not (pg_bin / "postgres.exe").is_file() or not openssl.is_file():
        raise RuntimeError("Provide portable PostgreSQL 16 binaries and local OpenSSL first")
    version = subprocess.check_output([str(pg_bin / "postgres.exe"), "--version"], text=True)
    if "PostgreSQL) 16." not in version:
        raise RuntimeError("This validation runner requires PostgreSQL 16")
    print(version.strip(), flush=True)
    sandbox = Path(tempfile.mkdtemp(prefix="postgres-staging-", dir=TOOLS))
    data = sandbox / "data"
    password = secrets.token_urlsafe(36)
    user = "kuzenga_validation"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    database = "kuzenga_staging_" + uuid.uuid4().hex[:12]
    password_file = sandbox / "initdb-password"
    password_file.write_text(password + "\n", encoding="utf-8")
    try:
        subprocess.run(
            [str(pg_bin / "initdb.exe"), "-D", str(data), "-U", user, "--encoding=UTF8", "--locale=C",
             "--auth-host=scram-sha-256", "--auth-local=scram-sha-256", "--pwfile=" + str(password_file)],
            text=True, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Local initdb failed: " + (exc.stderr or "no diagnostic output")) from exc
    finally:
        password_file.unlink(missing_ok=True)
    subprocess.run(
        [str(openssl), "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
         "-keyout", str(data / "server.key"), "-out", str(data / "server.crt")],
        check=True, capture_output=True,
    )
    with (data / "postgresql.conf").open("a", encoding="utf-8") as configuration:
        configuration.write("\nssl=on\nlisten_addresses='127.0.0.1'\n")
    pg_ctl = [str(pg_bin / "pg_ctl.exe"), "-D", str(data)]
    subprocess.run([*pg_ctl, "-l", str(sandbox / "server.log"), "-o", f"-p {port}", "-w", "start"], check=True)
    try:
        parameters = {"host": "127.0.0.1", "port": port, "user": user, "password": password, "sslmode": "require"}
        with psycopg.connect(dbname="postgres", autocommit=True, **parameters) as connection:
            if not connection.pgconn.ssl_in_use:
                raise RuntimeError("Local validation requires TLS")
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        url = f"postgresql://{user}:{password}@127.0.0.1:{port}/{database}?sslmode=require"
        # Local generated credentials, never cloud credentials. This folder is ignored.
        (sandbox / "state.json").write_text(json.dumps({"database_url": url}), encoding="utf-8")
        environment = {
            **os.environ, "DATABASE_URL": url, "DIRECT_DATABASE_URL": url,
            "DEPLOYMENT_ENVIRONMENT": "staging", "VERCEL_ENV": "preview", "VERCEL": "0",
            "DJANGO_SECRET_KEY": secrets.token_urlsafe(64), "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
            "DJANGO_SETTINGS_MODULE": "config.settings.production", "DIRECT_UPLOADS_ENABLED": "False",
            "MEDIA_STORAGE_BACKEND": "filesystem",
        }
        arguments = ["scripts/migrate_preview.py", "--expected-host", "127.0.0.1", "--expected-database", database]
        for command in (["manage.py", "check"], arguments, [*arguments, "--apply"]):
            subprocess.run([sys.executable, *command], cwd=PROJECT, env=environment, check=True)
        environment["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
        selected = []
        if args.finance_only:
            environment["KUZENGA_RUN_PG_ACCEPTANCE"] = "1"
            selected = [str(path.relative_to(PROJECT)) for path in sorted((PROJECT / "tests").glob("test_finance*.py"))]
        subprocess.run([sys.executable, "manage.py", "check"], cwd=PROJECT, env=environment, check=True)
        subprocess.run(
            [sys.executable, "-m", "pytest", "-ra", "--tb=short", "--maxfail=4", "--reuse-db", "-p", "no:cacheprovider",
             "--basetemp", str(sandbox / "pytest-temp"), *selected],
            cwd=PROJECT, env=environment, check=True,
        )
    finally:
        subprocess.run([*pg_ctl, "-m", "fast", "-w", "stop"], check=True)
        print("Local PostgreSQL validation data retained in " + str(sandbox) + "; server stopped.", flush=True)


if __name__ == "__main__":
    main()
