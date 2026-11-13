"""Inspect explicitly selected SQLite migration metadata without writing to it."""
import json
import sqlite3
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as db:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    applied = set(db.execute('SELECT app, name FROM django_migrations')) if 'django_migrations' in tables else set()
    integrity = db.execute('PRAGMA quick_check').fetchone()[0]
root = Path(__file__).resolve().parents[1]
result = {'integrity': integrity, 'applications': {}}
for folder in sorted((root / 'apps').glob('*/migrations')):
    names = sorted(path.stem for path in folder.glob('[0-9]*.py'))
    app = folder.parent.name
    result['applications'][app] = {'applied': [name for name in names if (app, name) in applied],
                                    'pending': [name for name in names if (app, name) not in applied]}
print(json.dumps(result, indent=2))
