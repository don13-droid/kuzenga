"""Index only the public marketing site; keep application responses private."""

from django.core.exceptions import DisallowedHost
from django.http import HttpResponse
from django.views.decorators.http import require_safe

PUBLIC_ORIGIN = "https://www.elevondigitalzw.com"
PUBLIC_HOST = "www.elevondigitalzw.com"
PUBLIC_PATHS = ("/", "/elevon/")


def is_public_origin(request):
    """Use Django's validated Host and trusted HTTPS handling."""
    if not request.is_secure():
        return False
    try:
        host = request.get_host().lower()
    except DisallowedHost:
        return False
    return host in (PUBLIC_HOST, f"{PUBLIC_HOST}:443")


class IndexingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        indexable = (
            response.status_code == 200
            and request.method in ("GET", "HEAD")
            and request.path_info in PUBLIC_PATHS
            and not request.GET
            and is_public_origin(request)
        )
        if not indexable:
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response


@require_safe
def robots(request):
    if is_public_origin(request):
        body = (
            "User-agent: *\n"
            "Disallow: /\n"
            "Allow: /$\n"
            "Allow: /elevon/$\n"
            "Allow: /static/\n"
            "Allow: /sitemap.xml$\n"
            f"Sitemap: {PUBLIC_ORIGIN}/sitemap.xml\n"
        )
    else:
        body = "User-agent: *\nDisallow: /\n"
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


@require_safe
def sitemap(request):
    entry = f"<url><loc>{PUBLIC_ORIGIN}/</loc></url>" if is_public_origin(request) else ""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entry}</urlset>\n"
    )
    return HttpResponse(body, content_type="application/xml; charset=utf-8")
