from django.urls import path

from . import views

app_name = "admissions"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("applications/", views.application_list, name="list"),
    path("applications/new/", views.application_create, name="create"),
    path("applications/<uuid:pk>/", views.application_detail, name="detail"),
    path("applications/<uuid:pk>/edit/", views.application_edit, name="edit"),
    path("applications/<uuid:pk>/enrol/", views.application_enrol, name="enrol"),
    path("applications/<uuid:pk>/documents/<uuid:document_id>/", views.document_download, name="document-download"),
]
