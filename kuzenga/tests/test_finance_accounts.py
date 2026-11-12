# ruff: noqa: F811
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.context import tenant_context
from apps.finance.models import FeeRule, StudentAccount
from apps.finance.services import configure, reverse_journal
from apps.finance.student_accounts import statement, sync_enrolled_accounts
from apps.students.models import Student, StudentEnrolment
from tests.conftest import make_class
from tests.test_finance_foundation import finance, post  # noqa: F401


@pytest.mark.django_db
def test_statements_opening_currency_and_historical_student(finance):
    with tenant_context(finance["tenant"]):
        journal = post(finance)
        post(finance, reference="ZIG-1", idempotency_key="zig1", currency=finance["zig"])
        reverse_journal(
            journal,
            member=finance["approver"],
            reference="REV1",
            idempotency_key="rev1",
            date=date(2026, 2, 2),
            period=finance["period"],
            reason="Correction",
        )
        result = statement(finance["maker"], finance["student"], finance["usd"], start=date(2026, 2, 2))
        assert result["opening"] == Decimal("100.10")
        assert result["closing"] == Decimal(0)
        assert len(result["rows"]) == 1
        assert result["rows"][0]["balance"] == 0
        student = finance["student"].student
        student.status = "withdrawn"
        student.save()
        assert statement(finance["maker"], finance["student"], finance["zig"])["outstanding"] == Decimal("100.10")


@pytest.mark.django_db
def test_sync_is_idempotent_and_does_not_post(finance):
    from apps.finance.models import Journal

    with tenant_context(finance["tenant"]):
        classroom = make_class(finance["tenant"])
        student = Student.objects.create(admission_number="NEW", first_name="New", last_name="Learner")
        StudentEnrolment.objects.create(student=student, class_group=classroom, effective_from=date(2026, 1, 1))
        assert sync_enrolled_accounts(finance["approver"]) == 1
        assert sync_enrolled_accounts(finance["approver"]) == 0
        assert StudentAccount.objects.filter(student=student).count() == 1
        assert not Journal.objects.exists()
        with pytest.raises(PermissionDenied):
            sync_enrolled_accounts(finance["maker"])


@pytest.mark.django_db
def test_authorised_enrolment_creates_account_without_charge(finance):
    from apps.finance.models import Journal
    from apps.students.services import enrol_student

    with tenant_context(finance["tenant"]):
        classroom = make_class(finance["tenant"])
        student = Student.objects.create(admission_number="AUTO", first_name="Automatic", last_name="Account")
        enrol_student(student, classroom, actor=finance["approver"].user, effective_from=date(2026, 1, 1))
        assert StudentAccount.objects.filter(student=student).count() == 1
        assert not Journal.objects.exists()


@pytest.mark.django_db
def test_fee_overlap_precision_and_history(finance):
    with tenant_context(finance["tenant"]):
        classroom = make_class(finance["tenant"])
        values = dict(
            code="TUITION",
            name="Tuition",
            academic_year=classroom.academic_year,
            currency=finance["usd"],
            amount=Decimal("100.00"),
            income_account=finance["income"],
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 4, 30),
            due_date=date(2026, 1, 31),
        )
        fee = configure(FeeRule, values, finance["approver"])
        with pytest.raises(ValidationError):
            configure(FeeRule, {**values, "grade": classroom.grade}, finance["approver"])
        with pytest.raises(ValidationError):
            configure(FeeRule, {**values, "code": "LAB", "amount": Decimal("1.001")}, finance["approver"])
        replacement = configure(
            FeeRule,
            {**values, "amount": Decimal("120"), "effective_from": date(2026, 5, 1), "effective_to": date(2026, 8, 31)},
            finance["approver"],
        )
        assert replacement.pk != fee.pk
        with pytest.raises(ValidationError):
            FeeRule.objects.filter(pk=fee.pk).update(amount=200)
        with pytest.raises(ValidationError):
            fee.save()


@pytest.mark.django_db
def test_account_and_fee_pages_and_foreign_access(client, finance):
    from apps.tenancy.models import Role
    from tests.conftest import make_tenant, make_user

    client.force_login(finance["approver"].user)
    for url in [
        "/finance/students/",
        "/finance/fees/",
        "/finance/fees/new/",
        f"/finance/students/{finance['student'].pk}/",
    ]:
        assert client.get(url).status_code == 200
    response = client.get(f"/finance/students/{finance['student'].pk}/", {"currency": str(finance["usd"].pk)})
    assert response.status_code == 200
    client.force_login(finance["maker"].user)
    assert client.get("/finance/fees/new/").status_code == 200
    other = make_tenant("foreign-finance", "professional")
    user = make_user(other, Role.ADMIN)
    client.force_login(user)
    assert client.get(f"/finance/students/{finance['student'].pk}/").status_code == 404
    with tenant_context(other):
        from apps.finance.forms import FeeRuleForm

        assert not FeeRuleForm().fields["currency"].queryset.filter(pk=finance["usd"].pk).exists()
