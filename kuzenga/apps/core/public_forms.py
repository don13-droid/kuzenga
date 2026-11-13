from django import forms

from .pricing import PLANS


class DemoEnquiryForm(forms.Form):
    name = forms.CharField(max_length=120)
    organisation = forms.CharField(label='School or organisation', max_length=200)
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=40)
    enrolment = forms.IntegerField(label='Student enrolment', min_value=0, max_value=1000000)
    plan = forms.ChoiceField(label='Interested plan', choices=[(p, p.title()) for p in (*PLANS, 'enterprise')])
    message = forms.CharField(max_length=4000, widget=forms.Textarea)
    consent = forms.BooleanField(label='I agree to be contacted about this enquiry.')
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self):
        if self.cleaned_data['website']:
            raise forms.ValidationError('Unable to accept this enquiry.')
        return ''
