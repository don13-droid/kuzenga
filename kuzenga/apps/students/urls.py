from django.urls import path

from . import views

app_name = "students"
urlpatterns = [
    path("", views.student_list, name="list"),
    path("new/", views.student_create, name="create"),
    path("<uuid:pk>/", views.student_detail, name="detail"),
    path("<uuid:pk>/edit/", views.student_edit, name="edit"),
    path("<uuid:pk>/documents/<uuid:document_id>/", views.document_download, name="document-download"),
]
