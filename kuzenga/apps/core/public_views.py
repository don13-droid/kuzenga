import logging
from smtplib import SMTPException

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import DemoEnquiry
from .pricing import ADDONS, BANDS, FEATURES
from .public_forms import DemoEnquiryForm

logger = logging.getLogger(__name__)


@require_http_methods(['GET', 'POST'])
def home(request):
    form = DemoEnquiryForm(request.POST if request.method == 'POST' else None)
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            signing.loads(request.POST.get('enquiry_token', ''), salt='demo-enquiry', max_age=3600)
        except signing.BadSignature:
            form.add_error(None, 'Please reload this page before submitting your enquiry.')
        else:
            # Hash rather than retain network identifiers. A shared cache is required for multi-worker throttling.
            from django.utils.crypto import salted_hmac
            key = 'demo-enquiry:' + salted_hmac('demo-enquiry', request.META.get('REMOTE_ADDR', '')).hexdigest()
            if not cache.add(key, True, timeout=60):
                form.add_error(None, 'Please wait a minute before sending another enquiry.')
                status = 429
            else:
                values = {key: value for key, value in form.cleaned_data.items() if key != 'website'}
                lead = DemoEnquiry.objects.create(**values)
                try:
                    send_mail('New Kuzenga demo enquiry', f'Enquiry {lead.pk} received. Review securely in the database.',
                              settings.DEFAULT_FROM_EMAIL, ['sales@elevondigitalzw.com'])
                except (SMTPException, OSError):
                    logger.warning('Demo enquiry saved; email notification unavailable')
                return redirect(reverse('corporate-home') + '?sent=1#contact')
    return render(request, 'public/home.html', {
        'form': form, 'sent': request.GET.get('sent') == '1',
        'enquiry_token': signing.dumps('demo', salt='demo-enquiry'),
        'bands': BANDS, 'addons': ADDONS, 'features': FEATURES,
        'pricing': {'bands': BANDS, 'addons': ADDONS},
    }, status=status)
