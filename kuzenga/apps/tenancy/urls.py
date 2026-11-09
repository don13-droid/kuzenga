from django.urls import path

from . import user_admin_views, views

app_name = "tenancy"
urlpatterns = [
    path("select/", views.select_tenant, name="select"),
    path("users/", user_admin_views.school_user_directory, name="users"),
    path("users/create/", user_admin_views.school_user_create, name="user-create"),
    path("users/roles/", user_admin_views.school_user_roles, name="user-roles"),
    path("users/<uuid:membership_id>/", user_admin_views.school_user_profile, name="user-profile"),
    path("users/<uuid:membership_id>/edit/", user_admin_views.school_user_edit, name="user-edit"),
    path("users/<uuid:membership_id>/status/", user_admin_views.school_user_status, name="user-status"),
    path("users/<uuid:membership_id>/invite/", user_admin_views.school_user_invite, name="user-invite"),
    path("users/<uuid:membership_id>/password-reset/", user_admin_views.school_user_password_reset, name="user-password-reset"),
]
