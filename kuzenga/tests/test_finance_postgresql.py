"""Opt-in, committed multi-connection tests; only Django's disposable PostgreSQL DB.

No db/transactional_db fixture: their flush would intentionally conflict with the
append-only ledger guards. django_db_setup creates and destroys the whole test DB.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction

from apps.core.context import tenant_context
from apps.finance.models import Journal, Payment, PaymentAllocation, Receipt
from apps.finance.services import ledger_totals
from apps.finance.workflows import allocate_payment, confirm_payment, invoice_outstanding
from tests.test_finance_foundation import finance
from tests.test_finance_workflows import bill, core, pay

pytestmark = pytest.mark.skipif(
    os.environ.get("KUZENGA_RUN_PG_ACCEPTANCE") != "1" or connection.vendor != "postgresql",
    reason="Requires explicit opt-in and an isolated PostgreSQL DATABASE_URL.",
)


@pytest.fixture(autouse=True)
def catalogue(django_db_setup, django_db_blocker):
    # Override conftest's transactional catalogue fixture: workers need committed rows.
    from django.core.management import call_command

    with django_db_blocker.unblock():
        call_command("seed_catalog")


def test_postgresql_concurrent_financial_invariants(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        assert connection.vendor == "postgresql"
        assert connection.settings_dict["NAME"].startswith("test_"), "Refusing a non-test database"
        data = core.__wrapped__(finance.__wrapped__(None))
        with tenant_context(data["tenant"]):
            invoice = bill(data)[0]

        def race(operation):
            barrier = Barrier(2)

            def worker(index):
                close_old_connections()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SET lock_timeout = '10s'")
                        cursor.execute("SET statement_timeout = '20s'")
                    with tenant_context(data["tenant"]):
                        barrier.wait(timeout=10)
                        return operation(index)
                finally:
                    connection.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, index) for index in range(2)]
                return [future.result(timeout=30) for future in futures]

        def duplicate(_index):
            payment = pay(data, value="50", key="concurrent-same")
            return confirm_payment(member=data["maker"], payment=payment, period=data["period"]).pk

        receipts = race(duplicate)
        assert receipts[0] == receipts[1]
        with tenant_context(data["tenant"]):
            assert Receipt.objects.count() == 1
            assert Payment.objects.count() == 1
            # Bulk billing retries must also serialize without creating a second charge.
        assert len(set(race(lambda _index: bill(data)[0].pk))) == 1
        with tenant_context(data["tenant"]):
            payments = [pay(data, value="75", key=f"allocation-race-{i}") for i in range(2)]
            for payment in payments:
                confirm_payment(member=data["maker"], payment=payment, period=data["period"], auto_allocate=False)

        def allocate(index):
            try:
                allocate_payment(member=data["maker"], payment=payments[index], invoice=invoice, value="75")
                return "allocated"
            except ValidationError:
                return "capacity-rejected"

        assert sorted(race(allocate)) == ["allocated", "capacity-rejected"]
        with tenant_context(data["tenant"]):
            assert invoice_outstanding(invoice) == 25
            assert sum(PaymentAllocation.objects.values_list("amount", flat=True), Decimal(0)) == 125
            count = Journal.objects.count()
            with pytest.raises(RuntimeError), transaction.atomic():
                payment = pay(data, key="rollback-request")
                confirm_payment(member=data["maker"], payment=payment, period=data["period"])
                raise RuntimeError("Intentional transaction rollback")
            assert Journal.objects.count() == count
            assert not Payment.objects.filter(idempotency_key="rollback-request").exists()
            for journal in Journal.objects.filter(posted=True):
                totals = ledger_totals(journal.lines.all())
                assert all(row["debits"] == row["credits"] for row in totals)
