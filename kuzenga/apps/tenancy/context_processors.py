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
        items.append({**item, "locked": bool(item["module"]) and item["module"] not in entitled})
    return {"tenant": tenant, "nav_items": items}
