"""The translation sheet, review progress and 'Suggest a better word' (ADR-060 items 11, 14)."""

from io import BytesIO
from typing import Any
from uuid import UUID

from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.platform import text_suggestions
from apps.platform.api import text_serializers as s
from apps.platform.api.views import PlatformView
from apps.platform.models import TextSuggestion
from common import languages, text_sheet
from common.tenancy import get_current_tenant_id

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class SuggestionCreateView(APIView):
    """Anyone signed in (staff, a shop's login, a super admin) may suggest a better word."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=s.SuggestionCreateSerializer,
        responses={201: s.SuggestionCreatedSerializer},
        operation_id="texts_suggestions_create",
        tags=["texts"],
    )
    def post(self, request: Request) -> Response:
        data = s.SuggestionCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        made = text_suggestions.suggest(
            request.user,  # type: ignore[arg-type]
            get_current_tenant_id(),
            text_suggestions.SuggestionInput(
                v["language"], v["screen"], v.get("current_text", ""), v["suggestion"]
            ),
        )
        return Response({"id": made.pk}, status=201)


class SuggestionListView(PlatformView, generics.ListAPIView[TextSuggestion]):
    required_permission = "platform.settings.manage"
    serializer_class = s.SuggestionSerializer

    def get_queryset(self) -> Any:
        f = s.SuggestionFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        return text_suggestions.suggestions(
            f.validated_data.get("status", ""), f.validated_data.get("language", "")
        )

    @extend_schema(
        parameters=[s.SuggestionFilterSerializer],
        operation_id="platform_text_suggestions_list",
        tags=["platform"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class SuggestionDetailView(PlatformView):
    required_permission = "platform.settings.manage"

    @extend_schema(
        request=s.SuggestionUpdateSerializer,
        responses=s.SuggestionSerializer,
        operation_id="platform_text_suggestions_update",
        tags=["platform"],
    )
    def patch(self, request: Request, suggestion_id: UUID) -> Response:
        data = s.SuggestionUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        found = text_suggestions.resolve(
            suggestion_id,
            data.validated_data["status"],
            by=request.user,  # type: ignore[arg-type]
        )
        return Response(s.SuggestionSerializer(found).data)


class TextProgressView(PlatformView):
    required_permission = "platform.settings.manage"

    @extend_schema(
        responses=s.TextProgressSerializer(many=True),
        operation_id="platform_texts_progress",
        tags=["platform"],
    )
    def get(self, request: Request) -> Response:
        enabled = set(languages.enabled())
        waiting = dict(
            TextSuggestion.objects.filter(status=TextSuggestion.Status.NEW)
            .values_list("language")
            .annotate(n=Count("id"))
        )
        rows = []
        for found in text_sheet.progress():
            lang = languages.get(found.code)
            assert lang is not None
            rows.append(
                {
                    "code": found.code,
                    "name": lang.name,
                    "native": lang.native,
                    "enabled": found.code in enabled,
                    "total": found.total,
                    "translated": found.translated,
                    "reviewed": found.reviewed,
                    "new_suggestions": waiting.get(found.code, 0),
                }
            )
        return Response(s.TextProgressSerializer(rows, many=True).data)


class TextSheetView(PlatformView):
    """Every text in one spreadsheet, for a translator (the same as ``texts_export``)."""

    required_permission = "platform.settings.manage"

    @extend_schema(
        responses={(200, XLSX): OpenApiResponse(OpenApiTypes.BINARY)},
        operation_id="platform_texts_sheet",
        tags=["platform"],
    )
    def get(self, request: Request) -> HttpResponse:
        stream = BytesIO()
        count = text_sheet.export(stream)
        audit.record("platform.texts_exported", metadata={"texts": count}, tenant_id=None)
        response = HttpResponse(stream.getvalue(), content_type=XLSX)
        name = f"texts-{timezone.localdate():%Y-%m-%d}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response
