"""Compliance APIs (PLAN §3.10): the distributor's GST provider credentials and e-invoices."""

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.compliance import cancellation, credentials, einvoice, selectors
from apps.compliance.api import serializers as s
from apps.compliance.models import DocumentType, EInvoiceRecord
from common.errors import InvalidFields, NotFound
from common.permissions import HasPermission

TAGS = ["compliance"]
MANAGE = "compliance.manage"


class Newest(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("-created_at", "-id")


class GstCredentialsView(APIView):
    permission_classes = [HasPermission]
    required_permission = "settings.manage"

    @extend_schema(operation_id="gst_credentials", tags=TAGS, responses=s.GstCredentialsSerializer)
    def get(self, request: Request) -> Response:
        credentials.require_module()
        return Response(
            s.GstCredentialsSerializer(credentials.describe(credentials.current())).data
        )

    @extend_schema(
        operation_id="gst_credentials_save",
        tags=TAGS,
        request=s.GstCredentialsInputSerializer,
        responses=s.GstCredentialsSerializer,
    )
    def put(self, request: Request) -> Response:
        data = s.GstCredentialsInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = credentials.save(
            data.validated_data["environment"],
            data.validated_data["values"],
            by=cast(User, request.user),
        )
        return Response(s.GstCredentialsSerializer(credentials.describe(row)).data)


class GstCredentialsVerifyView(APIView):
    permission_classes = [HasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        operation_id="gst_credentials_verify",
        tags=TAGS,
        request=None,
        responses=s.GstCredentialsSerializer,
    )
    def post(self, request: Request) -> Response:
        row = credentials.request_check()
        return Response(s.GstCredentialsSerializer(credentials.describe(row)).data)


# --- E-invoices ----------------------------------------------------------------------------------


class EInvoiceListView(generics.ListAPIView[EInvoiceRecord]):
    permission_classes = [HasPermission]
    required_permission = MANAGE
    serializer_class = s.EInvoiceRowSerializer
    pagination_class = Newest

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return EInvoiceRecord.objects.none()
        q = self.request.query_params
        status, kind = q.get("status", ""), q.get("document_type", "")
        if status and status not in EInvoiceRecord.Status.values:
            raise InvalidFields({"status": ["Not a valid e-invoice status."]})
        if kind and kind not in DocumentType.values:
            raise InvalidFields({"document_type": ["Choose invoice or credit note."]})
        return selectors.einvoice_list(selectors.Filters(status, kind, q.get("search", "")))

    def paginate_queryset(self, queryset: Any) -> Any:
        page = super().paginate_queryset(queryset)
        return [selectors.row(r) for r in page] if page is not None else None

    @extend_schema(
        operation_id="einvoices_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("status", str, enum=list(EInvoiceRecord.Status.values)),
            OpenApiParameter("document_type", str, enum=list(DocumentType.values)),
            OpenApiParameter("search", str, description="Document number, shop name or IRN"),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class EInvoiceDetailView(APIView):
    permission_classes = [HasPermission]
    required_permission = MANAGE

    @extend_schema(operation_id="einvoices_retrieve", tags=TAGS, responses=s.EInvoiceRowSerializer)
    def get(self, request: Request, record_id: UUID) -> Response:
        found = selectors.einvoice_list(selectors.Filters()).filter(pk=record_id).first()
        if found is None:
            raise NotFound()
        return Response(s.EInvoiceRowSerializer(selectors.row(found)).data)


class EInvoiceCountsView(APIView):
    permission_classes = [HasPermission]
    required_permission = MANAGE

    @extend_schema(operation_id="einvoices_counts", tags=TAGS, responses=s.EInvoiceCountsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.EInvoiceCountsSerializer(selectors.counts()).data)


class EInvoiceCancelView(APIView):
    permission_classes = [HasPermission]
    required_permission = MANAGE

    @extend_schema(
        operation_id="einvoice_cancel",
        tags=TAGS,
        request=s.EInvoiceCancelSerializer,
        responses=s.EInvoiceRowSerializer,
    )
    def post(self, request: Request, record_id: UUID) -> Response:
        data = s.EInvoiceCancelSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        cancellation.request(
            record_id,
            reason_code=v["reason_code"],
            remarks=v["remarks"],
            outcome=v["outcome"],
            to_backorder=v["to_backorder"],
            by=cast(User, request.user),
        )
        found = selectors.einvoice_list(selectors.Filters()).get(pk=record_id)
        return Response(s.EInvoiceRowSerializer(selectors.row(found)).data)


class _RequestIrn(APIView):
    permission_classes = [HasPermission]
    required_permission = MANAGE
    document_type = ""

    def _request(self, request: Request, document_id: UUID) -> Response:
        record = einvoice.request(self.document_type, document_id, by=cast(User, request.user))
        found = selectors.einvoice_list(selectors.Filters()).get(pk=record.pk)
        return Response(s.EInvoiceRowSerializer(selectors.row(found)).data)


class InvoiceEInvoiceView(_RequestIrn):
    document_type = DocumentType.INVOICE

    @extend_schema(
        operation_id="invoice_einvoice_request",
        tags=TAGS,
        request=None,
        responses=s.EInvoiceRowSerializer,
    )
    def post(self, request: Request, invoice_id: UUID) -> Response:
        return self._request(request, invoice_id)


class CreditNoteEInvoiceView(_RequestIrn):
    document_type = DocumentType.CREDIT_NOTE

    @extend_schema(
        operation_id="credit_note_einvoice_request",
        tags=TAGS,
        request=None,
        responses=s.EInvoiceRowSerializer,
    )
    def post(self, request: Request, note_id: UUID) -> Response:
        return self._request(request, note_id)
