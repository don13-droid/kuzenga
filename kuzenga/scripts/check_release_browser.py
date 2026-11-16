"""Real Chromium smoke checks using a disposable, loopback-only Django app."""

import io
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def prepare(database, password):
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

    from apps.tenancy.models import Role
    from tests.conftest import make_tenant, make_user

    call_command("migrate", interactive=False, verbosity=0, stdout=io.StringIO())
    call_command("seed_catalog", stdout=io.StringIO())
    school = make_user(make_tenant("browser-smoke", "professional"), Role.ADMIN)
    school.set_password(password)
    school.save(update_fields=["password"])
    platform = get_user_model().objects.create_superuser(
        "platform-browser@example.test", password,
    )
    return school.email, platform.email


def no_overflow(page):
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= innerWidth + 1"
    ), "Horizontal page overflow"


def public_checks(page, origin):
    for width in (320, 390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.goto(origin + "/").status == 200
        expect(page.locator("#quote")).not_to_have_text("")
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


def main():
    password = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="kuzenga-browser-") as directory:
        school_email, platform_email = prepare(Path(directory) / "browser.sqlite3", password)
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
                browser.close()
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
