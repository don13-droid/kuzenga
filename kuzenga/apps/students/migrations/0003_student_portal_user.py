from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


CONSTRAINT_NAME = "uniq_student_portal_user"


def add_portal_user_constraint(apps, schema_editor):
    student = apps.get_model("students", "Student")
    if schema_editor.connection.vendor == "sqlite":
        # SQLite's AddConstraint rebuilds this referenced table. A unique index
        # enforces the same invariant without disturbing existing foreign keys.
        quote = schema_editor.quote_name
        schema_editor.execute(
            f"CREATE UNIQUE INDEX {quote(CONSTRAINT_NAME)} ON "
            f"{quote(student._meta.db_table)} "
            f"({quote('tenant_id')}, {quote('portal_user_id')})"
        )
    else:
        # PostgreSQL must own a real constraint, matching AddConstraint's state
        # and future Django RemoveConstraint/AlterConstraint operations.
        schema_editor.add_constraint(student, models.UniqueConstraint(
            fields=("tenant", "portal_user"), name=CONSTRAINT_NAME,
        ))


def remove_portal_user_constraint(apps, schema_editor):
    student = apps.get_model("students", "Student")
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.execute(f"DROP INDEX {schema_editor.quote_name(CONSTRAINT_NAME)}")
    else:
        schema_editor.remove_constraint(student, models.UniqueConstraint(
            fields=("tenant", "portal_user"), name=CONSTRAINT_NAME,
        ))


class Migration(migrations.Migration):
    dependencies = [
        ("students", "0002_student_management"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="portal_user",
            field=models.ForeignKey(
                blank=True, db_index=False,
                help_text="An active student account at this school. Linking never changes an account's role.",
                null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="student_profiles", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(
                add_portal_user_constraint, remove_portal_user_constraint,
            )],
            state_operations=[migrations.AddConstraint(
                model_name="student",
                constraint=models.UniqueConstraint(
                    fields=("tenant", "portal_user"), name=CONSTRAINT_NAME,
                ),
            )],
        ),
    ]
