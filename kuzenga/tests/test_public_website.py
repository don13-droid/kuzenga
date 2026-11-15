import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from apps.core.models import DemoEnquiry
from apps.core.pricing import ADDONS, BANDS, PLANS, quote


@pytest.mark.parametrize('band', BANDS)
@pytest.mark.parametrize('plan', PLANS)
def test_price_band_boundaries(band, plan):
    result = quote(band['limit'], plan)
    assert result['subscription'] == band['prices'][PLANS.index(plan)]
    assert result['setup'] == band['setup']
    assert result['annual'] == 3 * result['subscription']
    assert result['first_term'] == result['subscription'] + result['setup']
    if band['limit'] < 2000:
        assert quote(band['limit'] + 1, plan)['setup'] > result['setup']


def test_included_addons_and_custom_quotes():
    assert quote(100, 'professional', [a['code'] for a in ADDONS])['addons'] == 28
    assert quote(100, 'standard', ['library', 'inventory'])['addons'] == 0
    assert quote(100, 'starter', ['finance', 'finance'])['addons'] == 15
    assert quote(2001, 'starter') == {'custom': True}
    assert quote(0, 'enterprise') == {'custom': True}
    for count in (-1, 1.5, True):
        with pytest.raises(ValueError):
            quote(count, 'starter')


@pytest.mark.django_db
def test_public_home_and_login_links(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Elevating Ideas.' in response.content
    assert b'US$30' in response.content
    assert reverse('login').encode() in response.content
    assert reverse('platform-login').encode() in response.content
    assert client.get(reverse('corporate-home')).status_code == 200


def enquiry(client):
    response = client.get(reverse('corporate-home'))
    return dict(name='Test enquirer', organisation='Test school', email='demo@example.test', phone='0710000000',
                enrolment=100, plan='starter', message='Please arrange a demo.', consent='on',
                enquiry_token=response.context['enquiry_token'])


@pytest.mark.django_db
def test_enquiry_validation_storage_email_and_throttle(client, settings):
    from django.core.cache import cache
    cache.clear()
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    data = enquiry(client)
    client.post(reverse('corporate-home'), {**data, 'consent': ''})
    client.post(reverse('corporate-home'), {**data, 'website': 'spam'})
    client.post(reverse('corporate-home'), {**data, 'enquiry_token': 'invalid'})
    assert not DemoEnquiry.objects.exists()
    assert client.post(reverse('corporate-home'), data).status_code == 302
    assert DemoEnquiry.objects.count() == 1
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ['info@elevondigitalzw.com']
    assert data['email'] not in mail.outbox[0].body
    assert client.post(reverse('corporate-home'), data).status_code == 429
    assert DemoEnquiry.objects.count() == 1
    assert Client(enforce_csrf_checks=True).post(reverse('corporate-home'), data).status_code == 403


@pytest.mark.django_db
def test_leads_are_platform_only(client, admin_a):
    from django.contrib.auth import get_user_model
    data = enquiry(client)
    values = {key: value for key, value in data.items() if key != 'enquiry_token'}
    values['consent'] = True
    lead = DemoEnquiry.objects.create(**values)
    route = reverse('admin:core_demoenquiry_change', args=[lead.pk])
    assert client.get(route).status_code == 302
    client.force_login(admin_a)
    assert client.get(route).status_code == 302
    platform = get_user_model().objects.create_superuser('lead-admin@example.test', 'unused-password')
    client.force_login(platform)
    assert client.get(route).status_code == 200
    assert client.post(route, {'name': 'tamper'}).status_code == 403
    lead.refresh_from_db()
    assert lead.name == data['name']


@pytest.mark.django_db
def test_authenticated_root_is_public_and_dashboard_still_available(client, admin_a):
    client.force_login(admin_a)
    assert b'Elevating Ideas.' in client.get('/').content
    assert b'Welcome' in client.get(reverse('dashboard')).content
    assert reverse('dashboard') == '/dashboard/'


@pytest.mark.django_db
def test_redesigned_home_has_supplied_brand_photos_and_private_previews(client):
    from django.contrib.staticfiles import finders
    response = client.get('/')
    html = response.content.decode()
    for asset in ('elevon-logo', 'students-learning', 'teacher-classroom', 'digital-team', 'kuzenga-students', 'kuzenga-admissions'):
        path = 'images/corporate/' + asset + '.png'
        assert path in html
        assert finders.find(path)
    assert 'Privacy-edited student directory preview' in html
    assert 'Privacy-edited admissions preview' in html
    assert 'data-preview="students"' in html and 'data-preview="admissions"' in html
    assert 'aria-label="Mobile navigation"' in html
    assert 'School Login' in html and 'Student Login' in html


def test_serverless_and_project_landing_templates_stay_in_sync():
    from pathlib import Path

    from django.conf import settings

    project = Path(settings.BASE_DIR)
    template = (project / "templates/public/home.html").read_text(encoding="utf-8")
    assert template == (project / "apps/core/templates/public/home.html").read_text(encoding="utf-8")
    assert "{{ portal_login_url }}" in template
    assert "{{ platform_login_url }}" in template
    assert "mailto:info@elevondigitalzw.com" in template
    assert "&copy; 2026 Elevon Digital. All rights reserved." in template
