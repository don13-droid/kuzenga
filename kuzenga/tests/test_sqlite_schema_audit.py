import sqlite3
import unittest

from scripts.audit_sqlite_schema import differences, schema


class SchemaDriftTests(unittest.TestCase):
    def setUp(self):
        self.expected = sqlite3.connect(':memory:')
        self.actual = sqlite3.connect(':memory:')
        self.addCleanup(self.expected.close)
        self.addCleanup(self.actual.close)
        for db in (self.expected, self.actual):
            db.executescript('''
                CREATE TABLE parent (id integer PRIMARY KEY);
                CREATE TABLE child (id integer PRIMARY KEY, parent_id integer REFERENCES parent(id), value integer CHECK(value >= 0));
                CREATE UNIQUE INDEX child_value_idx ON child(value);
                CREATE TRIGGER child_guard BEFORE DELETE ON child BEGIN SELECT RAISE(ABORT, 'protected'); END;
            ''')

    def test_identical_schema_and_different_data_are_not_drift(self):
        self.actual.execute('INSERT INTO parent VALUES (1)')
        result = differences(schema(self.actual), schema(self.expected))
        self.assertFalse(any(result.values()))
        self.assertEqual(len(schema(self.actual)), 4)

    def test_missing_index_trigger_and_unexpected_column_are_detected(self):
        self.actual.executescript('''
            DROP INDEX child_value_idx;
            DROP TRIGGER child_guard;
            ALTER TABLE child ADD COLUMN extra text;
        ''')
        result = differences(schema(self.actual), schema(self.expected))
        self.assertIn('index:child_value_idx', result['missing_objects'])
        self.assertIn('trigger:child_guard', result['missing_objects'])
        self.assertIn('columns', result['changed_objects']['table:child'])

    def test_changed_foreign_key_and_check_constraint_are_detected(self):
        self.actual.executescript('''
            DROP TABLE child;
            CREATE TABLE child (id integer PRIMARY KEY, parent_id integer, value integer CHECK(value > 10));
        ''')
        changed = differences(schema(self.actual), schema(self.expected))['changed_objects']['table:child']
        self.assertIn('foreign_keys', changed)
        self.assertIn('definition', changed)


if __name__ == '__main__':
    unittest.main()
