"""Synthetic loopback-only finance acceptance app; never opens the working database."""
import io
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
folder = PROJECT / "build" / ("finance-browser-" + uuid.uuid4().hex[:12])
folder.mkdir(parents=True)
os.environ.update(DJANGO_SETTINGS_MODULE="config.settings.test", DATABASE_URL="sqlite:///" + (folder / "acceptance.sqlite3").as_posix(),
                  MEDIA_STORAGE_BACKEND="filesystem", DIRECT_UPLOADS_ENABLED="False", VERCEL="0")

import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.core.wsgi import get_wsgi_application  # noqa: E402

settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
settings.STATIC_URL = "/static/"
call_command("migrate", verbosity=0, stdout=io.StringIO())
call_command("seed_catalog", stdout=io.StringIO())
from apps.core.context import tenant_context  # noqa: E402
from apps.finance.controls import request_control  # noqa: E402
from apps.finance.models import Account, StatementRow  # noqa: E402
from apps.finance.operations import decide_import, preview_import, request_match  # noqa: E402
from apps.finance.services import configure, student_account  # noqa: E402
from apps.finance.workflows import confirm_payment  # noqa: E402
from apps.students.models import Student, StudentEnrolment  # noqa: E402
from tests.test_finance_foundation import finance  # noqa: E402
from tests.test_finance_workflows import bill, core, pay  # noqa: E402

data = core.__wrapped__(finance.__wrapped__(None))
with tenant_context(data["tenant"]):
    second = Student.objects.create(admission_number="B1", first_name="Bea", last_name="Browser")
    StudentEnrolment.objects.create(student=second, class_group=data["class"], effective_from=date(2026, 1, 1))
    secondary = student_account(second, data["maker"])
    invoice = bill(data, students=[second.pk])[0]
    bank = configure(Account, dict(code="BANK", name="Acceptance bank", kind="asset", purpose="bank"), data["approver"])
    contra = configure(Account, dict(code="CON", name="Concessions", kind="expense", purpose="concession"), data["approver"])
    opening = configure(Account, dict(code="OPEN", name="Opening funds", kind="equity", purpose="opening"), data["approver"])
    source = pay(data, student=secondary, value="200", key="browser-source", receiving_account=bank, method="bank_transfer", external_reference="BROWSER-BANK")
    confirm_payment(member=data["maker"], payment=source, period=data["period"], verified=True, verification_reference="Synthetic statement", auto_allocate=False)
    defaults = dict(member=data["maker"], mode="fixed", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
                    eligibility="Synthetic acceptance eligibility", reason="Synthetic acceptance request", supporting_reference="TEST-ONLY")
    concession = request_control(kind="discount", invoice=invoice, counter_account=contra, value="10", benefit_code="BROWSER-CON", idempotency_key="browser-con", **defaults)
    refund = request_control(kind="refund", payment=source, counter_account=bank, value="20", benefit_code="BROWSER-REF", idempotency_key="browser-ref", **defaults)
    statement = preview_import(member=data["maker"], kind="statement", source="date,reference,amount\n2026-02-02,BROWSER-BANK,200\n", source_name="acceptance-bank.csv", account=bank, currency=data["usd"])
    decide_import(member=data["approver"], batch=statement, approved=True, reason="Synthetic source checked")
    row = StatementRow.objects.get(batch=statement)
    proposal = request_match(member=data["maker"], row=row, line=source.decision.journal.lines.get(account=bank), reason="Synthetic exact match", idempotency_key="browser-match")
    opening_batch = preview_import(member=data["maker"], kind="opening", source="student_reference,currency,amount,reference\nB1,ZIG,-10,LEGACY-BROWSER\n", source_name="acceptance-opening.csv", receivable=data["receivable"], offset=opening)


class QuietHandler(WSGIRequestHandler):
    def log_message(self, _format, *args):
        pass


from django.contrib.staticfiles.handlers import StaticFilesHandler  # noqa: E402

server = make_server("127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
details = {k: str(data[k].pk) for k in ["fee", "cash", "period", "receivable", "usd", "student", "income"]}
details.update(origin=f"http://127.0.0.1:{server.server_port}", year=str(data["class"].academic_year_id),
               concession=str(concession.pk), refund=str(refund.pk), match=str(proposal.pk), opening=str(opening_batch.pk), folder=str(folder))
print(json.dumps(details), flush=True)
server.serve_forever()
