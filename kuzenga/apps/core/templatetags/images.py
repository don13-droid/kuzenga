from django import template

register = template.Library()


@register.inclusion_tag("components/avatar.html")
def avatar(field, label, size="small"):
    url = ""
    if field and field.name:
        try:
            if field.storage.exists(field.name):
                url = field.url
        except OSError:
            pass
    return {"image_url": url, "label": label, "size": size}
