from xml.etree import ElementTree

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.core.seo import PUBLIC_HOST, PUBLIC_ORIGIN, IndexingMiddleware

PREVIEW_HOST = "preview.example.test"
PLATFORM_HOST = "platform.example.test"
CLIENT_HOST = "school.example.test"
NOINDEX = "noindex, nofollow, noarchive"

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_site(settings):
    settings.ALLOWED_HOSTS = [
        PUBLIC_HOST, PREVIEW_HOST, PLATFORM_HOST, CLIENT_HOST, "testserver",
    ]
    settings.PUBLIC_SITE_HOST = ""
    settings.PLATFORM_SITE_HOST = ""
    settings.CLIENT_SITE_HOST = ""


@pytest.mark.parametrize("method", ["get", "head"])
def test_canonical_marketing_page_is_indexable(client, public_site, method):
    response = getattr(client, method)("/", secure=True, HTTP_HOST=PUBLIC_HOST)
    assert response.status_code == 200
    assert "X-Robots-Tag" not in response


@pytest.mark.parametrize("path", [
    "/login/", "/platform/login/", "/dashboard/", "/students/",
    "/finance/debt/", "/health/", "/not-a-route/", "/?sent=1",
])
def test_private_redirect_error_and_query_responses_are_noindex(client, public_site, path):
    response = client.get(path, secure=True, HTTP_HOST=PUBLIC_HOST)
    assert response.status_code in (200, 302, 404)
    assert response["X-Robots-Tag"] == NOINDEX


def test_preview_home_is_not_indexable(client, public_site):
    response = client.get("/", secure=True, HTTP_HOST=PREVIEW_HOST)
    assert response.status_code == 200
    assert response["X-Robots-Tag"] == NOINDEX


def test_public_form_response_is_not_indexable(client, public_site):
    response = client.post("/", {}, secure=True, HTTP_HOST=PUBLIC_HOST)
    assert response.status_code == 200
    assert response["X-Robots-Tag"] == NOINDEX


def test_https_redirect_is_noindex(client, public_site, settings):
    settings.SECURE_SSL_REDIRECT = True
    response = client.get("/", HTTP_HOST=PUBLIC_HOST)
    assert response.status_code == 301
    assert response.url == f"{PUBLIC_ORIGIN}/"
    assert response["X-Robots-Tag"] == NOINDEX


@pytest.mark.parametrize("status", [302, 400, 403, 404, 405, 500, 503])
def test_error_and_redirect_headers_do_not_require_a_valid_host(status, public_site):
    request = RequestFactory().get("/", secure=True, HTTP_HOST="invalid.example.test")
    response = IndexingMiddleware(lambda _request: HttpResponse(status=status))(request)
    assert response.status_code == status
    assert response["X-Robots-Tag"] == NOINDEX


@pytest.mark.parametrize("host,secure", [
    (PUBLIC_HOST, False), (PREVIEW_HOST, True),
    (f"{PUBLIC_HOST}:8443", True), ("invalid.example.test", True),
])
def test_other_origins_are_not_indexable(host, secure, public_site):
    request = RequestFactory().get("/", secure=secure, HTTP_HOST=host)
    response = IndexingMiddleware(lambda _request: HttpResponse())(request)
    assert response["X-Robots-Tag"] == NOINDEX


def test_public_view_keeps_a_more_restrictive_header(public_site):
    request = RequestFactory().get("/", secure=True, HTTP_HOST=PUBLIC_HOST)
    response = HttpResponse(headers={"X-Robots-Tag": "noindex"})
    result = IndexingMiddleware(lambda _request: response)(request)
    assert result["X-Robots-Tag"] == "noindex"


def test_public_robots_and_sitemap_contain_only_public_content(client, public_site):
    robots = client.get("/robots.txt", secure=True, HTTP_HOST=PUBLIC_HOST)
    assert robots.status_code == 200
    assert robots["Content-Type"].startswith("text/plain")
    assert b"Disallow: /\nAllow: /$\n" in robots.content
    assert f"Sitemap: {PUBLIC_ORIGIN}/sitemap.xml".encode() in robots.content

    sitemap = client.get("/sitemap.xml", secure=True, HTTP_HOST=PUBLIC_HOST)
    assert sitemap.status_code == 200
    root = ElementTree.fromstring(sitemap.content)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    assert [item.text for item in root.findall(f"{ns}url/{ns}loc")] == [f"{PUBLIC_ORIGIN}/"]
    assert sitemap["X-Robots-Tag"] == NOINDEX


@pytest.mark.parametrize("host", [PREVIEW_HOST, PLATFORM_HOST, CLIENT_HOST])
def test_other_hosts_disallow_crawling_and_list_no_urls(client, public_site, host):
    robots = client.get("/robots.txt", secure=True, HTTP_HOST=host)
    assert robots.status_code == 200
    assert robots.content == b"User-agent: *\nDisallow: /\n"
    assert robots["X-Robots-Tag"] == NOINDEX
    sitemap = client.get("/sitemap.xml", secure=True, HTTP_HOST=host)
    assert sitemap.status_code == 200
    assert not list(ElementTree.fromstring(sitemap.content))
    assert sitemap["X-Robots-Tag"] == NOINDEX


@pytest.mark.parametrize("host", [PUBLIC_HOST, PLATFORM_HOST, CLIENT_HOST])
def test_portal_routing_keeps_discovery_endpoints(client, public_site, settings, host):
    settings.PUBLIC_SITE_HOST = PUBLIC_HOST
    settings.PLATFORM_SITE_HOST = PLATFORM_HOST
    settings.CLIENT_SITE_HOST = CLIENT_HOST
    for path in ("/robots.txt", "/sitemap.xml"):
        response = client.get(path, secure=True, HTTP_HOST=host)
        assert response.status_code == 200
        assert "Location" not in response


@pytest.mark.parametrize("path", ["/robots.txt", "/sitemap.xml"])
def test_discovery_supports_head_and_rejects_post(client, public_site, path):
    response = client.head(path, secure=True, HTTP_HOST=PUBLIC_HOST)
    assert response.status_code == 200
    assert response.content == b""
    response = client.post(path, {}, secure=True, HTTP_HOST=PUBLIC_HOST)
    assert response.status_code == 405
    assert response["X-Robots-Tag"] == NOINDEX
