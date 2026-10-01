from django.urls import path

from apps.search.api import views as v

urlpatterns = [
    path("search/", v.PlatformSearchView.as_view(), name="platform-search"),
    path("search/users/", v.PlatformUserSearchView.as_view(), name="platform-search-users"),
]
