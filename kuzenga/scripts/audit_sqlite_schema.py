"""Compare read-only SQLite schema with a disposable replay of its recorded migrations.

No model comparison against HEAD: unapplied migrations are legitimate pending
changes, not automatically drift. Prints object names/structure, never row data.
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path


def schema(db):
    objects = {}
    for kind, name, _table, sql in db.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall():
        if name == 'django_migrations':
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        details = {'definition': re.sub(r'\s+', ' ', sql or '').strip()}
        if kind == 'table':
            details['columns'] = list(db.execute(f'PRAGMA table_xinfo({quoted})'))
            details['foreign_keys'] = sorted(db.execute(f'PRAGMA foreign_key_list({quoted})'))
            details['indexes'] = sorted(
                (row[1], row[2], row[3], row[4]) for row in db.execute(f'PRAGMA index_list({quoted})')
            )
        objects[f'{kind}:{name}'] = details
    return objects


def differences(actual, expected):
    return {
        'missing_objects': sorted(expected.keys() - actual.keys()),
        'unexpected_objects': sorted(actual.keys() - expected.keys()),
        'changed_objects': {
            name: {field: {'actual': actual[name].get(field), 'expected': value}
                   for field, value in expected[name].items() if actual[name].get(field) != value}
            for name in sorted(actual.keys() & expected.keys()) if actual[name] != expected[name]
        },
    }


def main():
    source = Path(sys.argv[1]).resolve(strict=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
        applied = set(original.execute('SELECT app, name FROM django_migrations'))
        actual = schema(original)
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import django
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    executor = MigrationExecutor(connection)
    unknown = applied - set(executor.loader.disk_migrations)
    if unknown:
        raise RuntimeError(f'Cannot reproduce unknown recorded migrations: {sorted(unknown)}')
    missing_dependencies = {
        node: sorted(set(executor.loader.graph.forwards_plan(node)) - applied)
        for node in sorted(applied)
        if set(executor.loader.graph.forwards_plan(node)) - applied
    }
    if missing_dependencies:
        raise RuntimeError(f'Inconsistent recorded migration dependencies: {missing_dependencies}')
    targets = [node for node in sorted(applied)
               if not any(child.key in applied for child in executor.loader.graph.node_map[node].children)]
    executor.migrate(targets)
    with connection.cursor() as cursor:
        expected = schema(cursor)
    result = differences(actual, expected)
    result['recorded_migrations_replayed'] = len(applied)
    result['reference_objects'] = len(expected)
    result['schema_matches_recorded_state'] = not any(result[key] for key in (
        'missing_objects', 'unexpected_objects', 'changed_objects'
    ))
    print(json.dumps(result, indent=2))
    return 0 if result['schema_matches_recorded_state'] else 1


if __name__ == '__main__':
    sys.exit(main())
