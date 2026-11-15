"""Route the existing portals on explicitly configured production hostnames."""

import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseNotFound, HttpResponseRedirect
from django.http.request import split_domain_port
from django.urls import reverse

HOST_SETTINGS = ("PUBLIC_SITE_HOST", "PLATFORM_SITE_HOST", "CLIENT_SITE_HOST")
PLATFORM_PATHS = ("/platform/", "/admin/")
SHARED_PATHS = ("/health/", "/api/health/", "/static/", "/media/", "/uploads/")


def portal_url(host_setting, path):
    host = getattr(settings, host_setting, "")
    return f"https://{host}{path}" if host else path


class PortalHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.hosts = {name: getattr(settings, name, "") for name in HOST_SETTINGS}
        if not any(self.hosts.values()):
            return  # Local development and isolated previews keep their existing URLs.
        if not all(self.hosts.values()) or len(set(self.hosts.values())) != 3:
            raise ImproperlyConfigured("Configure three distinct public, platform and client hosts")
        for host in self.hosts.values():
            if len(host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in host.split(".")
            ):
                raise ImproperlyConfigured("Portal hosts must be exact lowercase DNS hostnames")
            if host not in settings.ALLOWED_HOSTS:
                raise ImproperlyConfigured("Portal hosts must be included in DJANGO_ALLOWED_HOSTS")

    def _move(self, request, host_setting, path=None):
        # Never forward credentials, CSRF tokens or form bodies across portal hosts.
        if request.method not in ("GET", "HEAD"):
            return HttpResponseNotFound()
        return HttpResponseRedirect(portal_url(host_setting, path or request.get_full_path()))

    def __call__(self, request):
        if not any(self.hosts.values()):
            return self.get_response(request)
        host, _port = split_domain_port(request.get_host())
        path = request.path_info
        if path.startswith(SHARED_PATHS):
            return self.get_response(request)
        if path == "/elevon/" and host in (self.hosts["PLATFORM_SITE_HOST"], self.hosts["CLIENT_SITE_HOST"]):
            return self._move(request, "PUBLIC_SITE_HOST")

        if host == self.hosts["PUBLIC_SITE_HOST"]:
            if path not in ("/", "/elevon/"):
                target = "PLATFORM_SITE_HOST" if path.startswith(PLATFORM_PATHS) else "CLIENT_SITE_HOST"
                return self._move(request, target)
        elif host == self.hosts["PLATFORM_SITE_HOST"]:
            if path == "/":
                route = "superuser:tenant-directory" if request.user.is_authenticated and request.user.is_superuser else "platform-login"
                return self._move(request, "PLATFORM_SITE_HOST", reverse(route))
            if path == reverse("login"):
                return self._move(request, "PLATFORM_SITE_HOST", reverse("platform-login"))
            if not path.startswith(PLATFORM_PATHS):
                return self._move(request, "CLIENT_SITE_HOST")
        elif host == self.hosts["CLIENT_SITE_HOST"]:
            if path == "/":
                route = "dashboard" if request.user.is_authenticated else "login"
                return self._move(request, "CLIENT_SITE_HOST", reverse(route))
            if path.startswith(PLATFORM_PATHS):
                return self._move(request, "PLATFORM_SITE_HOST")
        return self.get_response(request)
