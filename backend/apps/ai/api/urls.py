from django.urls import path

from apps.ai.api import assistant_views as av
from apps.ai.api import views as v

urlpatterns = [
    path("settings/ai-usage/", v.MyAiUsageView.as_view(), name="settings-ai-usage"),
    path("assistant/tools/", av.AssistantToolsView.as_view(), name="assistant-tools"),
    path("assistant/questions/", av.AssistantQuestionsView.as_view(), name="assistant-questions"),
    path(
        "assistant/questions/<uuid:question_id>/",
        av.AssistantQuestionView.as_view(),
        name="assistant-question",
    ),
]
