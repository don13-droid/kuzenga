"""Apply the rehearsed existing migrations to the explicitly selected local checkout.

Refuses remote databases, production settings and unexpected migration plans.
Creates and verifies a fresh SQLite backup before applying any migration.
"""
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

project = Path(sys.argv[1]).resolve(strict=True)
source = project / 'db.sqlite3'
if os.environ.get('VERCEL') == '1':
    raise RuntimeError('Refusing migrations in Vercel mode')
if not source.is_file() or not (project / 'manage.py').is_file():
    raise RuntimeError('Select the existing product checkout with its local SQLite database')
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.development'
os.environ['DATABASE_URL'] = 'sqlite:///' + source.as_posix()
sys.path.insert(0, str(project))
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402

if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
    raise RuntimeError('Refusing a non-SQLite database')
if Path(settings.DATABASES['default']['NAME']).resolve() != source:
    raise RuntimeError('Unexpected database target')
executor = MigrationExecutor(connection)
executor.loader.check_consistent_history(connection)
if executor.loader.detect_conflicts():
    raise RuntimeError('Migration graph conflicts')
plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
identifiers = [(migration.app_label, migration.name) for migration, backwards in plan]
if any(backwards for _, backwards in plan):
    raise RuntimeError('Refusing reverse migrations')
if len(plan) != 15 or any(app not in ('finance', 'attendance') for app, name in identifiers):
    raise RuntimeError('Migration plan changed; review the new plan before proceeding')
call_command('check')
call_command('migrate', plan=True)


def columns(db):
    result = {}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if table.startswith(('finance_', 'students_', 'tenancy_', 'accounts_', 'academics_', 'attendance_', 'assessments_', 'admissions_', 'core_')):
            quoted = '"' + table.replace('"', '""') + '"'
            result[table] = [row[1] for row in db.execute(f'PRAGMA table_info({quoted})')]
    return result


def digest(db, fields):
    result = {}
    for table, names in fields.items():
        quoted = ', '.join('"' + name.replace('"', '""') + '"' for name in names)
        rows = sorted(repr(row) for row in db.execute(f'SELECT {quoted} FROM "{table}"'))
        result[table] = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
    return result


backup = source.with_name('db.before-authorized-migrations.' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
    fields = columns(original)
    before = digest(original, fields)
    with sqlite3.connect(backup) as saved:
        original.backup(saved)
        if saved.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed')
        if saved.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Backup foreign-key check failed')
        if digest(saved, fields) != before:
            raise RuntimeError('Backup domain data differs from source')
        with sqlite3.connect(':memory:') as restored:
            saved.backup(restored)
            if restored.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or digest(restored, fields) != before:
                raise RuntimeError('Backup restore verification failed')
print('Verified backup and restore:', backup.name, flush=True)
call_command('migrate', interactive=False, verbosity=1)
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
    if digest(original, fields) != before:
        raise RuntimeError('Pre-existing domain data changed; stop and investigate. Backup retained.')
    if original.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('Post-migration integrity check failed')
    if original.execute('PRAGMA foreign_key_check').fetchall():
        raise RuntimeError('Post-migration foreign-key check failed')
executor = MigrationExecutor(connection)
if executor.migration_plan(executor.loader.graph.leaf_nodes()):
    raise RuntimeError('Pending migrations remain')
call_command('check')
call_command('showmigrations')
call_command('migrate', plan=True)
call_command('makemigrations', check=True, dry_run=True)
print('SUCCESS: 15 existing migrations applied; original domain rows preserved; verified backup retained.')
