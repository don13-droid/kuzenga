from django.urls import path

from . import views

app_name = "academics"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("progression/", views.progression, name="progression"),
    path("classes/<uuid:pk>/", views.class_detail, name="class-detail"),
    path("years/", views.resource_list, {"kind": "years"}, name="years"),
    path("terms/", views.resource_list, {"kind": "terms"}, name="terms"),
    path("classes/", views.resource_list, {"kind": "classes"}, name="classes"),
    path("subjects/", views.resource_list, {"kind": "subjects"}, name="subjects"),
    path("allocations/", views.resource_list, {"kind": "allocations"}, name="allocations"),
    path("<str:kind>/", views.resource_list, name="list"),
    path("<str:kind>/new/", views.resource_create, name="create"),
    path("<str:kind>/<uuid:pk>/edit/", views.resource_create, name="edit"),
    path("<str:kind>/<uuid:pk>/deactivate/", views.resource_toggle, name="deactivate"),
]
