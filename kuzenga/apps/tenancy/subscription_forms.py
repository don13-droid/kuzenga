from django import forms

from .configuration_forms import StyledFormMixin
from .models import Plan, Subscription


class SubscriptionForm(StyledFormMixin, forms.ModelForm):
    reason = forms.CharField(max_length=255, widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = Subscription
        fields = ("plan", "status", "started_at", "current_period_end", "trial_ends_at")
        widgets = {
            name: forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
            for name in ("started_at", "current_period_end", "trial_ends_at")
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = Plan.objects.filter(is_active=True).order_by("name")
