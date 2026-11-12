from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor

from apps.core.context import tenant_context
from apps.students.models import Student, StudentEnrolment, StudentGuardian

from .conftest import make_class


@contextmanager
def migration_sandbox(django_db_blocker):
    """Start from an empty schema, never reverse unrelated irreversible migrations."""
    alias = "migration_" + uuid4().hex
    configuration = deepcopy(connection.settings_dict)
    configuration["AUTOCOMMIT"] = True
    if connection.vendor == "sqlite":
        configuration["NAME"] = ":memory:"
    connections.databases[alias] = configuration
    with django_db_blocker.unblock():
        sandbox = connections[alias]
        try:
            if sandbox.vendor == "postgresql":
                with sandbox.cursor() as cursor:
                    cursor.execute("CREATE SCHEMA " + sandbox.ops.quote_name(alias))
                    cursor.execute("SET search_path TO " + sandbox.ops.quote_name(alias))
            yield sandbox
        finally:
            # PostgreSQL schemas are retained in the isolated test database.
            # No existing schema/database is dropped or reset by this helper.
            sandbox.close()
            del connections[alias]
            connections.databases.pop(alias)


@pytest.mark.django_db
def test_student_management_migration_preserves_legacy_records(tenant_a, django_db_blocker):
    with migration_sandbox(django_db_blocker) as sandbox:
        check_student_upgrade(sandbox, tenant_a)


def check_student_upgrade(sandbox, tenant_a):
    group = make_class(tenant_a)
    before = [("students", "0001_initial")]
    executor = MigrationExecutor(sandbox)
    after = executor.loader.graph.leaf_nodes()
    executor.migrate(before)
    old_apps = executor.loader.project_state(before).apps

    def copy_fixture(app_label, model_name, instance):
        historical = old_apps.get_model(app_label, model_name)
        historical.objects.using(sandbox.alias).create(
            **{field.attname: getattr(instance, field.attname) for field in historical._meta.concrete_fields}
        )

    copy_fixture("tenancy", "Tenant", tenant_a)
    copy_fixture("academics", "AcademicYear", group.academic_year)
    copy_fixture("academics", "Grade", group.grade)
    copy_fixture("academics", "ClassGroup", group)
    student = (
        old_apps.get_model("students", "Student")
        .objects.using(sandbox.alias)
        .create(
            tenant_id=tenant_a.pk,
            admission_number="LEGACY-001",
            first_name="Existing",
            last_name="Learner",
        )
    )
    guardian = (
        old_apps.get_model("students", "Guardian")
        .objects.using(sandbox.alias)
        .create(
            tenant_id=tenant_a.pk,
            first_name="Existing",
            last_name="Guardian",
            phone="+263770000000",
        )
    )
    link = (
        old_apps.get_model("students", "StudentGuardian")
        .objects.using(sandbox.alias)
        .create(
            tenant_id=tenant_a.pk,
            student_id=student.pk,
            guardian_id=guardian.pk,
            is_primary=True,
        )
    )
    enrolment = (
        old_apps.get_model("students", "StudentEnrolment")
        .objects.using(sandbox.alias)
        .create(
            tenant_id=tenant_a.pk,
            student_id=student.pk,
            class_group_id=group.pk,
            effective_from=date(2026, 1, 5),
        )
    )
    MigrationExecutor(sandbox).migrate(after)
    with tenant_context(tenant_a):
        migrated = Student.objects.using(sandbox.alias).get(pk=student.pk)
        assert migrated.admission_number == "LEGACY-001" and migrated.first_name == "Existing"
        assert not migrated.profile_image
        migrated_link = StudentGuardian.objects.using(sandbox.alias).select_related("guardian").get(pk=link.pk)
        assert migrated_link.is_primary and not migrated_link.is_emergency
        assert migrated_link.guardian.phone == "+263770000000"
        assert StudentEnrolment.objects.using(sandbox.alias).get(pk=enrolment.pk).class_group_id == group.pk


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "sqlite", reason="SQLite-specific migration SQL check")
def test_additive_columns_do_not_rebuild_existing_sqlite_tables():
    sql = StringIO()
    call_command("sqlmigrate", "students", "0002", stdout=sql)
    assert "DROP TABLE" not in sql.getvalue()
