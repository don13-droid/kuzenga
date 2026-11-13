from django.urls import reverse

from .navigation import NAV_ITEMS
from .permissions import has_permission
from .services import active_module_codes


def tenancy(request):
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        return {"tenant": None, "nav_items": []}
    entitled = active_module_codes(tenant)
    items = []
    for item in NAV_ITEMS:
        if item["permission"] and not has_permission(request.membership, item["permission"]):
            continue
        items.append({**item, "href": reverse(item["url"]), "locked": bool(item["module"]) and item["module"] not in entitled})
    matches = [item for item in items if request.path == item["href"] or (
        item["href"] != "/" and request.path.startswith(item["href"])
    )]
    active = max(matches, key=lambda item: len(item["href"]), default=None)
    for item in items:
        item["active"] = item is active
    return {"tenant": tenant, "nav_items": items}
