from django import forms

from .context import get_current_tenant
from .models import TenantScopedModel


class TenantModelForm(forms.ModelForm):
    """ModelForm for tenant-owned models.

    - assigns the active tenant before validation so tenant-scoped unique constraints are checked
    - re-scopes every foreign-key dropdown to the active tenant
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.tenant_id is None:
            self.instance.tenant = get_current_tenant()
        for field in self.fields.values():
            if isinstance(field, forms.ModelChoiceField):
                model = field.queryset.model
                if issubclass(model, TenantScopedModel):
                    field.queryset = model.objects.all()

    def _get_validation_exclusions(self):
        exclude = super()._get_validation_exclusions()
        exclude.discard("tenant")
        return exclude
