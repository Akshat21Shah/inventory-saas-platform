from django.urls import include, path

from common.tests import views
from config.urls import urlpatterns as project_urlpatterns

urlpatterns = [
    *project_urlpatterns,
    path(
        "test-api/",
        include(
            [
                path("whoami/", views.WhoAmIView.as_view()),
                path("errors/", views.ErrorsView.as_view()),
                path("idempotent/", views.IdempotentView.as_view()),
                path("guarded/", views.GuardedView.as_view()),
                path("public/", views.PublicView.as_view()),
            ]
        ),
    ),
]
