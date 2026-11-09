from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.core.context import tenant_context
from apps.students.models import Student, StudentEnrolment, StudentGuardian

from .conftest import make_class


@pytest.mark.django_db(transaction=True)
def test_student_management_migration_preserves_legacy_records(tenant_a):
    group = make_class(tenant_a)
    before = [("students", "0001_initial")]
    executor = MigrationExecutor(connection)
    # Restore dependent apps too (admissions now depends on students.0002).
    after = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        student = old_apps.get_model("students", "Student").objects.create(
            tenant_id=tenant_a.pk, admission_number="LEGACY-001", first_name="Existing", last_name="Learner",
        )
        guardian = old_apps.get_model("students", "Guardian").objects.create(
            tenant_id=tenant_a.pk, first_name="Existing", last_name="Guardian", phone="+263770000000",
        )
        link = old_apps.get_model("students", "StudentGuardian").objects.create(
            tenant_id=tenant_a.pk, student_id=student.pk, guardian_id=guardian.pk, is_primary=True,
        )
        enrolment = old_apps.get_model("students", "StudentEnrolment").objects.create(
            tenant_id=tenant_a.pk, student_id=student.pk, class_group_id=group.pk, effective_from=date(2026, 1, 5),
        )
        MigrationExecutor(connection).migrate(after)
        with tenant_context(tenant_a):
            migrated = Student.objects.get(pk=student.pk)
            assert migrated.admission_number == "LEGACY-001" and migrated.first_name == "Existing"
            assert not migrated.profile_image
            migrated_link = StudentGuardian.objects.select_related("guardian").get(pk=link.pk)
            assert migrated_link.is_primary and not migrated_link.is_emergency
            assert migrated_link.guardian.phone == "+263770000000"
            assert StudentEnrolment.objects.get(pk=enrolment.pk).class_group_id == group.pk
    finally:
        MigrationExecutor(connection).migrate(after)


@pytest.mark.django_db(transaction=True)
def test_additive_columns_do_not_rebuild_existing_sqlite_tables():
    if connection.vendor != "sqlite":
        pytest.skip("SQLite-specific migration SQL check")
    sql = StringIO()
    call_command("sqlmigrate", "students", "0002", stdout=sql)
    assert "DROP TABLE" not in sql.getvalue()
