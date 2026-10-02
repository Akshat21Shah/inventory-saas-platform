from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.ai.api import assistant_serializers as s
from apps.ai.assistant import service
from apps.ai.assistant.tools import tools_for
from apps.ai.models import AssistantQuestion
from common.errors import NotFound
from common.pagination import DefaultCursorPagination
from common.permissions import FeatureOn, IsTenantStaff


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


class AssistantView(APIView):
    permission_classes = [IsTenantStaff, FeatureOn]
    required_feature = "ai"


class AssistantToolsView(AssistantView):
    """What the assistant may look at for this person (their reports; ADR-059)."""

    @extend_schema(
        operation_id="assistant_tools", tags=["assistant"], responses=s.AssistantToolsSerializer
    )
    def get(self, request: Request) -> Response:
        tools = [{"name": t.name, "report": t.report} for t in tools_for(_user(request))]
        return Response(s.AssistantToolsSerializer({"tools": tools}).data)


class AssistantQuestionsView(AssistantView, generics.ListAPIView[AssistantQuestion]):
    """The person's own questions, newest first; POST asks a new one (answered in the
    background: check the question until it isn't PENDING)."""

    serializer_class = s.AssistantQuestionSerializer
    pagination_class = DefaultCursorPagination

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):  # the schema, without a tenant
            return AssistantQuestion.objects.none()
        return AssistantQuestion.objects.filter(user=_user(self.request))

    @extend_schema(operation_id="assistant_questions_list", tags=["assistant"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="assistant_ask",
        tags=["assistant"],
        request=s.AskSerializer,
        responses={202: s.AssistantQuestionSerializer},
    )
    def post(self, request: Request) -> Response:
        data = s.AskSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        asked = service.ask(_user(request), data.validated_data["question"])
        return Response(s.AssistantQuestionSerializer(asked).data, status=202)


class AssistantQuestionView(AssistantView):
    @extend_schema(
        operation_id="assistant_question",
        tags=["assistant"],
        responses=s.AssistantQuestionSerializer,
    )
    def get(self, request: Request, question_id: UUID) -> Response:
        asked = AssistantQuestion.objects.filter(pk=question_id, user=_user(request)).first()
        if asked is None:
            raise NotFound()
        return Response(s.AssistantQuestionSerializer(asked).data)
