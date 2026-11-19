"""Real Chromium smoke checks using a disposable, loopback-only Django app."""

import csv
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def prepare(database, password):
    database = database.resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if (
        database.parent.parent != temporary_root
        or not database.parent.name.startswith("kuzenga-browser-")
        or database.name != "browser.sqlite3"
        or database.exists()
    ):
        raise RuntimeError("Browser acceptance requires a new disposable temporary database")
    os.environ.update(
        VERCEL="1",
        DJANGO_SETTINGS_MODULE="config.settings.test",
        DATABASE_URL="sqlite:///" + database.as_posix(),
        PUBLIC_SITE_HOST="",
        PLATFORM_SITE_HOST="",
        CLIENT_SITE_HOST="",
        DIRECT_UPLOADS_ENABLED="False",
        MEDIA_STORAGE_BACKEND="filesystem",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection
    from django.utils import timezone

    from apps.academics.models import AcademicYear, ClassGroup, Grade
    from apps.core.context import tenant_context
    from apps.tenancy.models import Membership, Role
    from tests.conftest import make_tenant, make_user

    if connection.vendor != "sqlite" or Path(connection.settings_dict["NAME"]).resolve() != database:
        raise RuntimeError("Refusing to migrate a database outside browser acceptance")
    call_command("migrate", interactive=False, verbosity=0, stdout=io.StringIO())
    call_command("seed_catalog", stdout=io.StringIO())
    tenant = make_tenant("browser-smoke", "professional")
    school = make_user(tenant, Role.ADMIN)
    bursar = make_user(tenant, Role.BURSAR)
    teacher = make_user(tenant, Role.TEACHER)
    student_login = make_user(tenant, Role.STUDENT)
    for user in (school, bursar, teacher, student_login):
        user.set_password(password)
        user.save(update_fields=["password"])
    today = timezone.localdate()
    year_start = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)
    with tenant_context(tenant):
        year = AcademicYear.objects.create(
            name=str(today.year), start_date=year_start, end_date=year_end, is_current=True,
        )
        grade = Grade.objects.create(name="Browser Grade", level_order=4)
        group = ClassGroup.objects.create(
            academic_year=year, grade=grade, name="Browser Class",
            class_teacher=Membership.objects.get(tenant=tenant, user=teacher),
        )
    platform = get_user_model().objects.create_superuser(
        "platform-browser@example.test", password,
    )
    return school.email, platform.email, {
        "database": str(database),
        "tenant_id": tenant.pk,
        "class_id": str(group.pk),
        "year_id": str(year.pk),
        "today": today.isoformat(),
        "year_start": year_start.isoformat(),
        "year_end": year_end.isoformat(),
        "bursar_email": bursar.email,
        "teacher_email": teacher.email,
        "student_email": student_login.email,
        "student_user_id": str(student_login.pk),
    }


def no_overflow(page):
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= innerWidth + 1"
    ), "Horizontal page overflow"


def public_checks(page, origin):
    for width in (320, 390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.goto(origin + "/").status == 200
        expect(page.locator("#pricing")).to_contain_text("From US$30")
        expect(page.locator("#pricing")).to_contain_text("Request a quotation")
        expect(page.locator("#quote")).to_have_count(0)
        page.evaluate(
            "() => Array.from(document.images).forEach(image => image.loading = 'eager')"
        )
        page.wait_for_function(
            "() => Array.from(document.images).every(image => "
            "image.complete && image.naturalWidth > 0)"
        )
        no_overflow(page)
        summary = page.locator(".mobile-nav summary")
        if summary.is_visible():
            summary.click()
            expect(page.locator(".mobile-nav")).to_have_attribute("open", "")
            page.keyboard.press("Escape")
            assert not page.locator(".mobile-nav").evaluate("element => element.open")
            expect(summary).to_be_focused()
        page.locator('[data-preview="admissions"]').click()
        expect(page.locator("#preview-admissions")).to_be_visible()
        expect(page.locator("#preview-students")).to_be_hidden()
        page.locator('[data-preview="students"]').click()
        expect(page.locator("#preview-students")).to_be_visible()
        no_overflow(page)
    print("PASS public browser: four widths, images, menu, previews, no overflow")


def drawer_checks(page, sidebar_selector, toggle_selector, overlay_selector, content_selector):
    sidebar = page.locator(sidebar_selector)
    toggle = page.locator(toggle_selector)
    page.set_viewport_size({"width": 390, "height": 844})
    expect(toggle).to_be_visible()
    expect(sidebar).to_be_hidden()
    toggle.click()
    expect(sidebar).to_be_visible()
    expect(sidebar).to_have_attribute("aria-modal", "true")
    assert page.locator(content_selector).evaluate("element => element.inert")
    assert sidebar.evaluate(
        "element => element.getBoundingClientRect().height <= innerHeight + 1"
    )
    controls = sidebar.locator(
        'a[href]:visible,button:visible,input:visible,select:visible,'
        'textarea:visible,[tabindex="0"]:visible'
    )
    expect(controls.first).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(controls.last).to_be_focused()
    page.keyboard.press("Tab")
    expect(controls.first).to_be_focused()
    links = sidebar.locator("nav a")
    assert links.count() > 0
    for link in links.all():
        link.scroll_into_view_if_needed()
        box = link.bounding_box()
        assert box and box["y"] >= -1 and box["y"] + box["height"] <= 845
    page.keyboard.press("Escape")
    expect(sidebar).to_be_hidden()
    expect(toggle).to_be_focused()
    toggle.click()
    page.locator(overlay_selector).click(position={"x": 386, "y": 15})
    expect(sidebar).to_be_hidden()
    expect(toggle).to_be_focused()
    no_overflow(page)
    page.set_viewport_size({"width": 1440, "height": 900})
    expect(sidebar).to_be_visible()
    expect(toggle).to_be_hidden()
    assert not page.locator(content_selector).evaluate("element => element.inert")
    no_overflow(page)


def authenticated_checks(browser, origin, email, password, platform=False):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    try:
        page = context.new_page()
        page.set_default_timeout(15000)
        path = "/platform/login/" if platform else "/login/"
        assert page.goto(origin + path).status == 200
        page.locator('input[name="username"]').fill(email)
        page.locator('input[name="password"]').fill(password)
        label = "Sign in to platform" if platform else "Sign in"
        page.get_by_role("button", name=label, exact=True).click()
        sidebar = "[data-navigation-sidebar]" if platform else "#school-sidebar"
        expect(page.locator(sidebar)).to_be_attached()
        assert "/login/" not in page.url
        if platform:
            drawer_checks(
                page, sidebar, "[data-navigation-toggle]",
                "[data-navigation-overlay]", "[data-navigation-content]",
            )
        else:
            drawer_checks(
                page, sidebar, ".school-sidebar-toggle",
                ".school-sidebar-overlay", ".school-content",
            )
        print("PASS platform login/drawer" if platform else "PASS school login/drawer")
    finally:
        context.close()


def workflow_state(fixture):
    """Read only our disposable database outside Playwright's event-loop thread."""
    def read():
        from django.db import connection, connections

        from apps.admissions.models import StudentApplication
        from apps.core.context import tenant_context
        from apps.core.models import AuditEvent
        from apps.finance.models import (
            Account,
            AccountingPeriod,
            Currency,
            FeeRule,
            Invoice,
            Journal,
            JournalLine,
            Payment,
            PaymentAllocation,
            Receipt,
            StudentAccount,
        )
        from apps.finance.workflows import invoice_outstanding, payment_state
        from apps.students.models import Student, StudentEnrolment, StudentGuardian
        from apps.tenancy.models import Tenant

        try:
            assert connection.vendor == "sqlite"
            assert Path(connection.settings_dict["NAME"]).resolve() == Path(fixture["database"])
            tenant = Tenant.objects.get(pk=fixture["tenant_id"])
            with tenant_context(tenant):
                application = StudentApplication.objects.first()
                student = Student.objects.filter(admission_number="BROWSER-0001").first()
                account = StudentAccount.objects.filter(student=student).first() if student else None
                invoice = Invoice.objects.first()
                payment = Payment.objects.first()
                receipt = Receipt.objects.first()
                currency = Currency.objects.filter(code="USD").first()
                fee = FeeRule.objects.filter(code="BROWSER-TUITION").first()
                period = AccountingPeriod.objects.first()
                balance = Decimal(0)
                if account:
                    balance = sum((
                        debit - credit for debit, credit in JournalLine.objects.filter(
                            student_account=account, journal__posted=True,
                        ).values_list("debit", "credit")
                    ), Decimal(0))
                return {
                    "application_count": StudentApplication.objects.count(),
                    "application_status": application.status if application else None,
                    "student_count": Student.objects.count(),
                    "enrolment_count": StudentEnrolment.objects.count(),
                    "guardian_link_count": StudentGuardian.objects.count(),
                    "student_id": str(student.pk) if student else None,
                    "portal_user_id": str(student.portal_user_id) if student and student.portal_user_id else None,
                    "student_account_id": str(account.pk) if account else None,
                    "invoice_count": Invoice.objects.count(),
                    "invoice_id": str(invoice.pk) if invoice else None,
                    "outstanding": invoice_outstanding(invoice) if invoice else None,
                    "payment_count": Payment.objects.count(),
                    "payment_state": payment_state(payment) if payment else None,
                    "payment_number": payment.number if payment else None,
                    "receipt_count": Receipt.objects.count(),
                    "receipt_id": str(receipt.pk) if receipt else None,
                    "receipt_snapshot": receipt.snapshot if receipt else None,
                    "allocation_count": PaymentAllocation.objects.count(),
                    "journal_count": Journal.objects.count(),
                    "balanced": all(
                        sum(j.lines.values_list("debit", flat=True), Decimal(0))
                        == sum(j.lines.values_list("credit", flat=True), Decimal(0))
                        for j in Journal.objects.filter(posted=True)
                    ),
                    "balance": balance,
                    "currency_id": str(currency.pk) if currency else None,
                    "fee_id": str(fee.pk) if fee else None,
                    "period_id": str(period.pk) if period else None,
                    "accounts": {a.code: str(a.pk) for a in Account.objects.all()},
                    "audit_actions": set(AuditEvent.objects.filter(tenant=tenant).values_list("action", flat=True)),
                }
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(read).result(timeout=20)


def workflow_login(context, origin, email, password):
    page = context.new_page()
    page.set_default_timeout(15000)
    assert page.goto(origin + "/login/").status == 200
    page.locator('input[name="username"]').fill(email)
    page.locator('input[name="password"]').fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator("#school-sidebar")).to_be_attached()
    assert "/login/" not in page.url
    return page


def save_configuration(page, origin, path, fields, selections, destination):
    assert page.goto(origin + path).status == 200
    for name, value in fields.items():
        page.locator(f'[name="{name}"]').fill(value)
    for name, value in selections.items():
        page.locator(f'select[name="{name}"]').select_option(value)
    page.get_by_role("button", name="Save configuration", exact=True).click()
    expect(page).to_have_url(origin + destination)


def critical_workflow_checks(browser, origin, school_email, password, fixture):
    """Actual CSRF-protected forms; only fixture identities/class are seeded."""
    parsed = urlsplit(origin)
    assert parsed.scheme == "http" and parsed.hostname == "localhost" and parsed.port
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        page = workflow_login(context, origin, school_email, password)
        assert page.goto(origin + "/admissions/applications/new/").status == 200
        for name, value in {
            "first_name": "Browser", "last_name": "Learner",
            "guardian_first_name": "Synthetic", "guardian_last_name": "Guardian",
            "guardian_phone": "+263770000001", "guardian_relationship": "Parent",
            "application_date": fixture["today"],
        }.items():
            page.locator(f'[name="{name}"]').fill(value)
        page.locator('select[name="intended_year"]').select_option(fixture["year_id"])
        page.locator('select[name="intended_class"]').select_option(fixture["class_id"])
        page.get_by_role("button", name="Save and submit", exact=True).click()
        expect(page).to_have_url(re.compile(re.escape(origin) + r"/admissions/applications/[0-9a-f-]+/$"))
        application_path = urlsplit(page.url).path
        expect(page.get_by_role("heading", name="Browser Learner", exact=True)).to_be_visible()
        for target in ("under_review", "accepted"):
            page.locator('select[name="target"]').select_option(target)
            page.locator('textarea[name="reason"]').fill("Disposable browser acceptance decision")
            page.get_by_role("button", name="Confirm status change", exact=True).click()
            expect(page).to_have_url(origin + application_path)
            if target == "under_review":
                expect(page.locator('select[name="target"] option[value="accepted"]')).to_have_count(1)
            else:
                expect(page.get_by_role("link", name="Enrol applicant", exact=True)).to_be_visible()
        page.get_by_role("link", name="Enrol applicant", exact=True).click()
        page.locator('select[name="class_group"]').select_option(fixture["class_id"])
        page.locator('input[name="effective_from"]').fill(fixture["today"])
        page.locator('input[name="admission_number"]').fill("BROWSER-0001")
        page.get_by_role("button", name="Confirm enrolment", exact=True).click()
        dialog = page.locator("#school-confirmation")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Confirm", exact=True).click()
        expect(page).to_have_url(origin + application_path)
        expect(page.get_by_role("heading", name="Enrolment completed", exact=True)).to_be_visible()
        state = workflow_state(fixture)
        assert state["application_status"] == "enrolled"
        assert state["application_count"] == state["student_count"] == state["enrolment_count"] == 1
        assert state["guardian_link_count"] == 1 and state["student_account_id"]
        assert state["journal_count"] == 0, "Enrolment must not create a financial charge"
        # Reopening a completed conversion cannot create another student.
        assert page.goto(origin + application_path + "enrol/").status == 200
        expect(page.get_by_role("button", name="Confirm enrolment", exact=True)).to_have_count(0)
        print("PASS browser admissions: submit, review, accept, guardian, enrol once; no charge")

        # Use the existing edit workflow to bind the newly enrolled learner's
        # separate Student login; retain their original student identity.
        student_path = "/students/" + state["student_id"] + "/"
        assert page.goto(origin + student_path + "edit/").status == 200
        expect(page.locator('input[name="first_name"]')).to_have_value("Browser")
        expect(page.locator('input[name="last_name"]')).to_have_value("Learner")
        page.locator('select[name="portal_user"]').select_option(fixture["student_user_id"])
        page.get_by_role("button", name="Save student", exact=True).click()
        expect(page).to_have_url(origin + student_path)
        assert workflow_state(fixture)["portal_user_id"] == fixture["student_user_id"]

        save_configuration(page, origin, "/finance/settings/currencies/", {
            "code": "USD", "name": "US dollar", "decimal_places": "2",
        }, {}, "/finance/accounts/")
        save_configuration(page, origin, "/finance/settings/periods/", {
            "name": "Browser accounting period", "starts_on": fixture["year_start"],
            "ends_on": fixture["year_end"],
        }, {}, "/finance/accounts/")
        for code, name, kind, purpose in (
            ("1200", "Student receivables", "asset", "receivable"),
            ("1100", "School bank", "asset", "bank"),
            ("4000", "Tuition income", "income", "tuition"),
        ):
            save_configuration(page, origin, "/finance/settings/accounts/", {
                "code": code, "name": name,
            }, {"kind": kind, "purpose": purpose}, "/finance/accounts/")
        state = workflow_state(fixture)
        save_configuration(page, origin, "/finance/fees/new/", {
            "code": "BROWSER-TUITION", "name": "Browser tuition", "amount": "150.00",
            "effective_from": fixture["year_start"], "effective_to": fixture["year_end"],
            "due_date": fixture["today"],
        }, {
            "academic_year": fixture["year_id"], "class_group": fixture["class_id"],
            "currency": state["currency_id"], "income_account": state["accounts"]["4000"],
        }, "/finance/fees/")
        expect(page.locator("body")).to_contain_text("Browser tuition")
        assert page.goto(origin + "/finance/payments/new/").status == 403, "Admin must not gain cashier posting"
    finally:
        context.close()

    context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    try:
        page = workflow_login(context, origin, fixture["bursar_email"], password)
        assert page.goto(origin + "/admissions/applications/new/").status == 403, "Cashier must not gain admissions authority"
        state = workflow_state(fixture)
        # Repeat the complete reviewed UI billing submission to check safe retries.
        for _attempt in range(2):
            assert page.goto(origin + "/finance/billing/").status == 200
            for name, value in {
                "fee": state["fee_id"], "period": state["period_id"],
                "receivable_account": state["accounts"]["1200"],
                "students": state["student_id"], "class_group": fixture["class_id"],
            }.items():
                page.locator(f'select[name="{name}"]').select_option(value)
            page.locator('input[name="date"]').fill(fixture["today"])
            page.get_by_role("button", name="Preview invoices", exact=True).click()
            expect(page.get_by_role("heading", name="Billing preview", exact=True)).to_be_visible()
            page.get_by_role("button", name="Confirm and post reviewed invoices", exact=True).click()
            expect(page).to_have_url(origin + "/finance/invoices/")
        state = workflow_state(fixture)
        assert state["invoice_count"] == state["journal_count"] == 1
        assert state["outstanding"] == state["balance"] == Decimal("150.00")

        assert page.goto(origin + "/finance/payments/new/").status == 200
        for name, value in {
            "student": state["student_account_id"], "currency": state["currency_id"],
            "method": "bank_transfer", "receiving_account": state["accounts"]["1100"],
            "receivable_account": state["accounts"]["1200"],
        }.items():
            page.locator(f'select[name="{name}"]').select_option(value)
        for name, value in {
            "value": "50.00", "on_date": fixture["today"],
            "external_reference": "BROWSER-BANK-001", "evidence_reference": "Synthetic statement only",
        }.items():
            page.locator(f'input[name="{name}"]').fill(value)
        page.get_by_role("button", name="Save configuration", exact=True).click()
        expect(page).to_have_url(re.compile(re.escape(origin) + r"/finance/payments/[0-9a-f-]+/$"))
        expect(page.locator("body")).to_contain_text("Status: pending")
        state = workflow_state(fixture)
        assert state["payment_count"] == 1 and state["receipt_count"] == 0
        assert state["balance"] == Decimal("150.00"), "Pending payment must not change balance"
        page.locator('select[name="period"]').select_option(state["period_id"])
        page.get_by_role("button", name="Confirm and post payment", exact=True).click()
        expect(page.locator("body")).to_contain_text("Verify the electronic payment independently")
        assert workflow_state(fixture)["receipt_count"] == 0
        page.locator('select[name="period"]').select_option(state["period_id"])
        page.locator('input[name="verified"]').check()
        page.locator('input[name="verification_reference"]').fill("SYNTHETIC-BROWSER-VERIFICATION")
        page.locator('input[name="auto_allocate"]').check()
        page.get_by_role("button", name="Confirm and post payment", exact=True).click()
        expect(page).to_have_url(re.compile(re.escape(origin) + r"/finance/receipts/[0-9a-f-]+/$"))
        expect(page.locator("body")).to_contain_text("Confirmed payment")
        expect(page.locator("body")).to_contain_text("Browser Learner")
        state = workflow_state(fixture)
        assert state["payment_state"] == "confirmed"
        assert state["payment_count"] == state["receipt_count"] == state["allocation_count"] == 1
        assert state["outstanding"] == state["balance"] == Decimal("100.00")
        assert state["journal_count"] == 2 and state["balanced"]
        assert Decimal(state["receipt_snapshot"]["amount"]) == Decimal("50.00")
        assert Decimal(state["receipt_snapshot"]["balance"]) == Decimal("100.00")
        assert {
            "admissions.enrolled", "finance.invoice_posted", "finance.payment_recorded",
            "finance.payment_confirmed", "finance.receipt_issued",
        } <= state["audit_actions"]
        pdf_url = page.get_by_role("link", name="Print PDF copy", exact=True).get_attribute("href")
        # Authenticated browser-context request verifies the actual generated file,
        # independently of Chromium's inline-PDF viewer/download implementation.
        pdf = context.request.get(origin + pdf_url)
        assert pdf.status == 200 and pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["cache-control"] == "private, no-store"
        assert pdf.body().startswith(b"%PDF-")

        for path in ("/finance/debt/", "/finance/collections/"):
            assert page.goto(origin + path).status == 200
            expect(page.locator("body")).to_contain_text("USD")
            page.set_viewport_size({"width": 390, "height": 844})
            no_overflow(page)
            page.set_viewport_size({"width": 1440, "height": 900})
        assert page.goto(origin + "/finance/reports/").status == 200
        page.locator('select[name="kind"]').select_option("collections")
        page.locator('select[name="currency"]').select_option(state["currency_id"])
        page.get_by_role("button", name="Preview", exact=True).click()
        expect(page.locator("tbody")).to_contain_text(state["payment_number"])
        expect(page.locator("tbody")).to_contain_text("confirmed")
        with page.expect_download() as download:
            page.get_by_role("button", name="Export CSV", exact=True).click()
        downloaded = download.value
        assert downloaded.failure() is None
        rows = list(csv.DictReader(Path(downloaded.path()).read_text(encoding="utf-8").splitlines()))
        assert len(rows) == 1 and rows[0]["Payment"] == state["payment_number"]
        assert rows[0]["Currency"] == "USD" and Decimal(rows[0]["Amount"]) == Decimal("50.00")
        assert rows[0]["Current status"] == "confirmed"
        print("PASS browser finance: configuration, fee, repeat-safe billing, pending/verified payment, allocation, receipt/PDF, debt/collections, CSV report")
    finally:
        context.close()


def learner_teacher_checks(browser, origin, password, fixture):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    try:
        page = workflow_login(context, origin, fixture["student_email"], password)
        expect(page.get_by_role("heading", name="My student dashboard", exact=True)).to_be_visible()
        expect(page.locator("#student-profile-heading")).to_have_text("My profile")
        expect(page.locator("body")).to_contain_text("Browser Learner")
        expect(page.locator("body")).to_contain_text("BROWSER-0001")
        expect(page.get_by_role("heading", name="Browser Class", exact=True)).to_be_visible()
        no_overflow(page)
        drawer_checks(page, "#school-sidebar", ".school-sidebar-toggle", ".school-sidebar-overlay", ".school-content")
        for path in ("/students/", "/finance/", "/school/users/", "/academics/", "/platform/tenants/"):
            assert page.goto(origin + path).status == 403, path
        assert page.goto(origin + "/dashboard/").status == 200
        account_menu = page.locator(".school-account-menu")
        account_menu.get_by_label("Account menu", exact=True).click()
        account_menu.get_by_role("button", name="Sign out", exact=True).click()
        expect(page).to_have_url(re.compile(re.escape(origin) + r"/login/"))
        page.goto(origin + "/dashboard/")
        expect(page).to_have_url(re.compile(re.escape(origin) + r"/login/"))
        print("PASS student browser: actual login, linked own profile/class, mobile drawer, private denials, sign out")
    finally:
        context.close()

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        page = workflow_login(context, origin, fixture["teacher_email"], password)
        assert page.goto(origin + "/academics/classes/" + fixture["class_id"] + "/").status == 200
        expect(page.locator("body")).to_contain_text("Browser Class")
        expect(page.locator("body")).to_contain_text("Browser Learner")
        expect(page.locator("body")).to_contain_text("BROWSER-0001")
        assert page.goto(origin + "/students/").status == 200
        expect(page.locator("body")).to_contain_text("Browser Learner")
        for path in ("/students/new/", "/finance/", "/school/users/", "/platform/tenants/"):
            assert page.goto(origin + path).status == 403, path
        print("PASS teacher browser: actual login/shared school workspace, assigned class roster, permitted students, private denials")
    finally:
        context.close()


def lighthouse_checks(origin, chrome_path, directory):
    environment = {**os.environ, "CHROME_PATH": chrome_path}
    for profile, flags in (("mobile", []), ("desktop", ["--preset=desktop"])):
        report_path = directory / f"lighthouse-{profile}.json"
        subprocess.run(
            [
                "npx", "--yes", "lighthouse@12.8.2", origin + "/",
                "--chrome-flags=--headless --no-sandbox --disable-dev-shm-usage",
                "--output=json", f"--output-path={report_path}", "--quiet", *flags,
            ],
            env=environment, check=True, timeout=180,
            stdout=subprocess.DEVNULL,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert not report.get("runtimeError"), "Lighthouse runtime failure"
        metrics = {}
        for name in (
            "largest-contentful-paint", "total-blocking-time",
            "cumulative-layout-shift", "speed-index", "total-byte-weight",
        ):
            audit = report["audits"].get(name, {})
            metrics[name] = audit.get("displayValue")
        scores = {
            name: round(category["score"] * 100)
            for name, category in report["categories"].items()
            if category.get("score") is not None
        }
        print("LIGHTHOUSE " + json.dumps({
            "profile": profile, "scores": scores, "metrics": metrics,
            "scope": "Isolated loopback app; noindex is intentional outside canonical HTTPS host.",
        }, sort_keys=True))


def main():
    password = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="kuzenga-browser-") as directory:
        school_email, platform_email, fixture = prepare(Path(directory) / "browser.sqlite3", password)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        origin = f"http://localhost:{port}"
        server = subprocess.Popen(
            [
                sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}",
                "--insecure", "--noreload",
            ],
            cwd=PROJECT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 30
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Disposable Django server exited during startup")
                try:
                    with urlopen(origin + "/health/", timeout=1) as response:
                        if response.status == 200:
                            break
                except (URLError, OSError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Disposable Django server did not become healthy")
                time.sleep(0.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_default_timeout(30000)
                public_checks(page, origin)
                page.close()
                authenticated_checks(browser, origin, school_email, password)
                authenticated_checks(browser, origin, platform_email, password, platform=True)
                critical_workflow_checks(browser, origin, school_email, password, fixture)
                learner_teacher_checks(browser, origin, password, fixture)
                browser.close()
                lighthouse_checks(origin, playwright.chromium.executable_path, Path(directory))
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            from django.db import connections

            connections.close_all()


if __name__ == "__main__":
    main()
