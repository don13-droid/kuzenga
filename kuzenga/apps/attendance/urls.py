from django.urls import path

from . import views

app_name = "attendance"
urlpatterns = [
    path("", views.today, name="today"),
    path("register/<uuid:class_id>/", views.register, name="register"),
]
