"""Imports, templates and exports (PLAN §3.5). The permission depends on the kind: products need
``products.manage``, retailers ``retailers.manage``."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.dataio import services
from apps.dataio.api import serializers as s
from apps.dataio.models import ImportJob
from common.errors import NotFound
from common.pagination import DefaultCursorPagination
from common.permissions import IsTenantStaff
from common.storage import get_storage

FILE = OpenApiResponse(OpenApiTypes.BINARY, description="Spreadsheet download")


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _require(request: Request, kind_code: str) -> None:
    if not _user(request).has_permission_code(services.kind_for(kind_code).permission):
        raise PermissionDenied()


def _allowed_kinds(request: Request) -> list[str]:
    user = _user(request)
    return [
        code for code, kind in services.KINDS.items() if user.has_permission_code(kind.permission)
    ]


def _job(request: Request, job_id: UUID) -> ImportJob:
    job: ImportJob | None = ImportJob.objects.filter(pk=job_id).first()
    if job is None or job.kind not in _allowed_kinds(request):
        raise NotFound()
    return job


def _download(data: bytes, content_type: str, file_name: str) -> HttpResponse:
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{file_name}"'
    response["Cache-Control"] = "private, no-store"
    return response


class ImportView(APIView):
    permission_classes = [IsTenantStaff]


class ImportListCreateView(ImportView, generics.ListAPIView[ImportJob]):
    serializer_class = s.ImportJobListSerializer
    pagination_class = DefaultCursorPagination
    filter_backends: list[Any] = []
    parser_classes = [MultiPartParser]

    def get_queryset(self) -> QuerySet[ImportJob]:
        if getattr(self, "swagger_fake_view", False):
            return ImportJob.objects.unscoped().none()
        return ImportJob.objects.filter(kind__in=_allowed_kinds(self.request)).select_related(
            "created_by"
        )

    @extend_schema(operation_id="imports_list", tags=["imports"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request={"multipart/form-data": s.ImportUploadSerializer},
        responses={201: s.ImportJobSerializer},
        operation_id="imports_create",
        tags=["imports"],
    )
    def post(self, request: Request) -> Response:
        data = s.ImportUploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _require(request, data.validated_data["kind"])
        job = services.create_job(
            data.validated_data["kind"],
            data.validated_data["mode"],
            data.validated_data["file"],
            by=_user(request),
        )
        return Response(s.ImportJobSerializer(job).data, status=201)


class ImportDetailView(ImportView):
    @extend_schema(
        responses=s.ImportJobSerializer, operation_id="imports_retrieve", tags=["imports"]
    )
    def get(self, request: Request, job_id: UUID) -> Response:
        return Response(s.ImportJobSerializer(_job(request, job_id)).data)


class ImportCommitView(ImportView):
    @extend_schema(
        request=None,
        responses=s.ImportJobSerializer,
        operation_id="imports_commit",
        tags=["imports"],
    )
    def post(self, request: Request, job_id: UUID) -> Response:
        job = services.request_commit(_job(request, job_id).pk, by=_user(request))
        return Response(s.ImportJobSerializer(job).data)


class ImportReportView(ImportView):
    @extend_schema(responses={200: FILE}, operation_id="imports_report", tags=["imports"])
    def get(self, request: Request, job_id: UUID) -> HttpResponse:
        job = _job(request, job_id)
        if not job.report_key:
            raise NotFound()
        name = job.file_name.rsplit(".", 1)[0][:80]
        return _download(get_storage().get(job.report_key), services.XLSX, f"{name}-report.xlsx")


class ImportTemplateView(ImportView):
    @extend_schema(responses={200: FILE}, operation_id="imports_template", tags=["imports"])
    def get(self, request: Request, kind: str) -> HttpResponse:
        kind = kind.upper()
        _require(request, kind)
        return _download(
            services.build_template(services.kind_for(kind), _user(request)),
            services.XLSX,
            f"{kind.lower()}-template.xlsx",
        )


class ExportView(ImportView):
    """Same columns as the import template, so a file can go out, be edited and come back."""

    kind_code = ""
    view_permission = ""

    @extend_schema(parameters=[s.ExportParamsSerializer], responses={200: FILE}, tags=["imports"])
    def get(self, request: Request) -> HttpResponse:
        if not _user(request).has_permission_code(self.view_permission):
            raise PermissionDenied()
        params = s.ExportParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        fmt = params.validated_data["file_type"]
        kind = services.kind_for(self.kind_code)
        data, content_type = services.build_export(kind, fmt, _user(request))
        return _download(data, content_type, f"{self.kind_code.lower()}.{fmt}")


class ProductExportView(ExportView):
    kind_code = "PRODUCTS"
    view_permission = "products.view"


class RetailerExportView(ExportView):
    kind_code = "RETAILERS"
    view_permission = "retailers.view"


class SpecialPriceExportView(ExportView):
    kind_code = "SPECIAL_PRICES"
    view_permission = "pricing.view"


class PriceListItemExportView(ExportView):
    kind_code = "PRICE_LIST_ITEMS"
    view_permission = "pricing.view"


class DiscountRuleExportView(ExportView):
    kind_code = "DISCOUNT_RULES"
    view_permission = "pricing.view"


class StockCountExportView(ExportView):
    """Today's stock in the opening-stock columns: count, edit and import with "Set stock"."""

    kind_code = "OPENING_STOCK"
    view_permission = "stock.adjust"
