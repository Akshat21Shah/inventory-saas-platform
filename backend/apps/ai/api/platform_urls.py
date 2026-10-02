from django.urls import path

from apps.ai.api import views as v

urlpatterns = [
    path("ai-usage/", v.PlatformAiUsageView.as_view(), name="platform-ai-usage"),
]
