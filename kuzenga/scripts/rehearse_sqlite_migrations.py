"""Rehearse migrations on an isolated SQLite snapshot; never write to the source.

Run from the product directory with an explicit source path. The snapshot contains
private data: keep it ignored and local; never attach it to a report or commit it.
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
handle, name = tempfile.mkstemp(prefix='migration-rehearsal-', suffix='.sqlite3', dir=Path.cwd())
os.close(handle)
snapshot = Path(name)
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original, sqlite3.connect(snapshot) as target:
    original.backup(target)
    assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'

os.environ['DATABASE_URL'] = 'sqlite:///' + snapshot.as_posix()
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import django  # noqa: E402

django.setup()
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402


def fingerprints():
    """Hash all pre-existing domain columns/rows without printing their values."""
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
        return {
            table: ([column.name for column in connection.introspection.get_table_description(cursor, table)])
            for table in tables if table.startswith(('finance_', 'students_', 'tenancy_', 'accounts_', 'academics_', 'attendance_', 'core_audit'))
        }


def digest(columns):
    result = {}
    with connection.cursor() as cursor:
        for table, fields in columns.items():
            sql_fields = ', '.join(connection.ops.quote_name(field) for field in fields)
            cursor.execute(f'SELECT {sql_fields} FROM {connection.ops.quote_name(table)}')
            rows = sorted(repr(row) for row in cursor.fetchall())
            result[table] = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
    return result


columns = fingerprints()
before = digest(columns)
executor = MigrationExecutor(connection)
executor.loader.check_consistent_history(connection)
assert not executor.loader.detect_conflicts()
plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
print('Pending migrations in snapshot:', len(plan))
call_command('migrate', interactive=False, verbosity=1)
assert digest(columns) == before, 'Pre-existing domain data changed during migration rehearsal'
executor = MigrationExecutor(connection)
assert not executor.migration_plan(executor.loader.graph.leaf_nodes())
call_command('check')
call_command('showmigrations')
call_command('migrate', plan=True)
call_command('makemigrations', check=True, dry_run=True)
with connection.cursor() as cursor:
    cursor.execute('PRAGMA integrity_check')
    assert cursor.fetchone()[0] == 'ok'
    cursor.execute('PRAGMA foreign_key_check')
    assert not cursor.fetchall()
print('Snapshot rehearsal passed; existing domain values preserved. Source database was opened read-only.')
print('Private snapshot retained locally:', snapshot.name)
