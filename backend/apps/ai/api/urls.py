from django.urls import path

from apps.ai.api import views as v

urlpatterns = [
    path("settings/ai-usage/", v.MyAiUsageView.as_view(), name="settings-ai-usage"),
]
