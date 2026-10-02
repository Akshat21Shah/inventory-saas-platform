"""Reports (PLAN §3.11, ADR-050): the catalogue a user may open, a page of rows with totals,
exports, and "My exports"."""

from datetime import date
from typing import Any
from uuid import UUID

from django.http import HttpResponse
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.reports import engine, selectors, services
from apps.reports.api import serializers as s
from apps.reports.models import ReportRun
from apps.reports.registry import Context, Report
from common.errors import InvalidFields, NotFound
from common.permissions import HasPermission, IsTenantStaff

TAGS = ["reports"]


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _default(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def describe(report: Report, user: User) -> dict[str, Any]:
    scope = engine.scope_for(user, report)
    return {
        "code": report.code,
        "title": report.title,
        "group": report.group,
        "description": report.description,
        "pdf": report.pdf,
        "background_only": report.background_only or report.sheets is not None,
        "max_days": report.max_days,
        "own_shops": scope.own_shops,
        "columns": [c.__dict__ for c in engine.columns(report, scope)],
        "filters": [
            {
                "key": f.key,
                "label": f.label,
                "kind": f.kind,
                "required": f.required,
                "choices": list(f.choices),
                "default": _default(f.default() if f.default else None),
                "entity": f.entity,
            }
            for f in report.filters
        ],
    }


def _int(value: str | None, field: str, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise InvalidFields({field: [_("A whole number.")]}) from exc


class ReportListView(APIView):
    permission_classes = [IsTenantStaff]

    @extend_schema(
        operation_id="reports_catalogue", tags=TAGS, responses=s.ReportSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        user = _user(request)
        reports = [describe(r, user) for r in engine.available(user)]
        return Response(s.ReportSerializer(reports, many=True).data)


class ReportView(APIView):
    permission_classes = [IsTenantStaff]

    @extend_schema(
        operation_id="reports_run",
        tags=TAGS,
        parameters=[
            OpenApiParameter("page", int),
            OpenApiParameter("page_size", int),
            OpenApiParameter(
                "filters",
                str,
                description="Each of the report's filters as its own query parameter "
                "(date_from, date_to, …); see the catalogue.",
            ),
        ],
        responses=s.ReportPageSerializer,
    )
    def get(self, request: Request, code: str) -> Response:
        user = _user(request)
        report = engine.get(code, user)
        q = request.query_params
        ctx = Context(engine.parse(report, q), engine.scope_for(user, report))
        page = engine.page(
            report,
            ctx,
            _int(q.get("page"), "page", 1),
            _int(q.get("page_size"), "page_size", engine.DEFAULT_PAGE_SIZE),
        )
        body = {**page.__dict__, "columns": [c.__dict__ for c in page.columns]}
        return Response(s.ReportPageSerializer(body).data)


class ReportExportView(APIView):
    permission_classes = [IsTenantStaff]

    @extend_schema(
        operation_id="reports_export",
        tags=TAGS,
        request=s.ExportRequestSerializer,
        responses={
            (200, "application/octet-stream"): OpenApiResponse(
                bytes, description="The file, when small enough to make at once"
            ),
            202: OpenApiResponse(
                s.ReportRunSerializer, description="Made in the background: see My exports"
            ),
        },
    )
    def post(self, request: Request, code: str) -> Response | HttpResponse:
        user = _user(request)
        report = engine.get(code, user)
        data = s.ExportRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        ctx = Context(
            engine.parse(report, data.validated_data["filters"]), engine.scope_for(user, report)
        )
        result = services.request_export(report, ctx, data.validated_data["format"], by=user)
        if isinstance(result, ReportRun):
            return Response(s.ReportRunSerializer(result).data, status=202)
        response = HttpResponse(result.data, content_type=result.content_type)
        response["Content-Disposition"] = f'attachment; filename="{result.name}"'
        return response


class Newest(CursorPagination):
    page_size = 20
    ordering = ("-created_at", "-id")


class ReportRunListView(generics.ListAPIView[ReportRun]):
    permission_classes = [IsTenantStaff]
    serializer_class = s.ReportRunSerializer
    pagination_class = Newest

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return ReportRun.objects.none()
        return selectors.runs_of(_user(self.request))

    @extend_schema(operation_id="report_runs_list", tags=TAGS)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class ReportRunView(APIView):
    permission_classes = [IsTenantStaff]

    @extend_schema(operation_id="report_runs_retrieve", tags=TAGS, responses=s.ReportRunSerializer)
    def get(self, request: Request, run_id: UUID) -> Response:
        run = selectors.runs_of(_user(request)).filter(pk=run_id).first()
        if run is None:
            raise NotFound()
        return Response(s.ReportRunSerializer(run).data)


class DashboardView(APIView):
    """What needs action today, today's figures and trends (ADR-050 item 11)."""

    permission_classes = [HasPermission]
    required_permission = "dashboard.view"

    @extend_schema(
        operation_id="dashboard", tags=["dashboard"], responses=s.DistributorDashboardSerializer
    )
    def get(self, request: Request) -> Response:
        from apps.reports.dashboard import dashboard

        return Response(s.DistributorDashboardSerializer(dashboard(_user(request))).data)
