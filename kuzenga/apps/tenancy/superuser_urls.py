from django.urls import path

from . import activity_views, configuration_views, subscription_views, user_admin_views, views

app_name = "superuser"

urlpatterns = [
    path("tenants/<uuid:tenant_id>/subscriptions/", subscription_views.tenant_subscriptions, name="tenant-subscriptions"),
    path("tenants/<uuid:tenant_id>/subscriptions/<uuid:subscription_id>/", subscription_views.tenant_subscriptions, name="tenant-subscription-edit"),
    path("activity/", activity_views.activity_overview, name="activity-overview"),
    path("activity/tenants/<uuid:tenant_id>/", activity_views.tenant_activity, name="tenant-activity"),
    path("activity/users/<uuid:user_id>/", activity_views.user_activity, name="user-activity"),
    path("activity/events/<uuid:event_id>/", activity_views.activity_event_detail, name="activity-event"),
    path("tenants/", views.tenant_directory, name="tenant-directory"),
    path("tenants/register/", views.tenant_registration, name="tenant-register"),
    path("tenants/register/cancel/", views.cancel_tenant_registration, name="tenant-register-cancel"),
    path("tenants/<uuid:tenant_id>/", views.tenant_overview, name="tenant-overview"),
    path("tenants/<uuid:tenant_id>/configure/", configuration_views.tenant_configuration, name="tenant-configuration"),
    path("tenants/<uuid:tenant_id>/configure/<slug:section>/", configuration_views.tenant_configuration_section, name="tenant-configuration-section"),
    path("tenants/<uuid:tenant_id>/configure/<slug:section>/<uuid:record_id>/", configuration_views.tenant_configuration_section, name="tenant-configuration-edit"),
    path("tenants/<uuid:tenant_id>/configure/<slug:section>/<uuid:record_id>/status/", configuration_views.tenant_configuration_toggle, name="tenant-configuration-toggle"),
    path("tenants/<uuid:tenant_id>/users/", user_admin_views.platform_user_directory, name="tenant-users"),
    path("tenants/<uuid:tenant_id>/users/create/", user_admin_views.platform_user_create, name="tenant-user-create"),
    path("tenants/<uuid:tenant_id>/users/roles/", user_admin_views.platform_user_roles, name="tenant-user-roles"),
    path("tenants/<uuid:tenant_id>/users/<uuid:membership_id>/", user_admin_views.platform_user_profile, name="tenant-user-profile"),
    path("tenants/<uuid:tenant_id>/users/<uuid:membership_id>/edit/", user_admin_views.platform_user_edit, name="tenant-user-edit"),
    path("tenants/<uuid:tenant_id>/users/<uuid:membership_id>/status/", user_admin_views.platform_user_status, name="tenant-user-status"),
    path("tenants/<uuid:tenant_id>/users/<uuid:membership_id>/invite/", user_admin_views.platform_user_invite, name="tenant-user-invite"),
    path("tenants/<uuid:tenant_id>/users/<uuid:membership_id>/password-reset/", user_admin_views.platform_user_password_reset, name="tenant-user-password-reset"),
    path("tenants/<uuid:tenant_id>/status/", views.tenant_overview_status, name="tenant-overview-status"),
    path("tenants/export/", views.tenant_directory_export, name="tenant-directory-export"),
    path("tenants/<uuid:tenant_id>/drawer/", views.tenant_directory_drawer, name="tenant-directory-drawer"),
]
