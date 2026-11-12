from django.urls import path

from . import views

app_name = "assessments"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("policies/new/", views.policy, name="policy"),
    path("configuration/<slug:kind>/", views.configuration, name="configuration"),
    path("results/", views.results, name="results"),
    path("analytics/", views.analytics, name="analytics"),
    path("examinations/", views.examinations, name="examinations"),
    path("students/<uuid:student_id>/", views.results, name="student-results"),
    path("students/<uuid:student_id>/terms/<uuid:term_id>/report.pdf", views.report, name="report"),
    path("students/<uuid:student_id>/terms/<uuid:term_id>/comment/", views.report_comment, name="report-comment"),
    path("<uuid:pk>/", views.detail, name="detail"),
    path("<uuid:pk>/schedule/", views.schedule, name="schedule"),
    path("<uuid:pk>/export.csv", views.export, name="export"),
]
