from django.urls import path

from apps.search.api import views as v

urlpatterns = [
    path("search/", v.SearchView.as_view(), name="search"),
]
