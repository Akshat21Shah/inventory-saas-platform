"""Retailers API (PLAN §3.6): reads ``retailers.view``, changes ``retailers.manage``, credit
terms ``credit.manage``. Sales staff may be limited to their own shops (PLAN B8)."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.retailers import selectors, services
from apps.retailers.api import serializers as s
from apps.retailers.models import Retailer
from common.errors import NotFound
from common.permissions import HasPermission

VIEW, MANAGE = "retailers.view", "retailers.manage"
READ_WRITE = {"GET": VIEW, "POST": MANAGE, "PUT": MANAGE, "PATCH": MANAGE, "DELETE": MANAGE}


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _visible(request: Request, retailer_id: UUID) -> Retailer:
    """404 for shops of other tenants and, for sales staff limited to their own, other shops."""
    retailer = selectors.retailer_for(_user(request), retailer_id)
    if retailer is None:
        raise NotFound()
    return retailer


def _detail(request: Request, retailer_id: UUID) -> dict[str, Any]:
    return dict(s.RetailerDetailSerializer(_visible(request, retailer_id)).data)


class RetailerView(APIView):
    permission_classes = [HasPermission]
    required_permissions = READ_WRITE


class NamePagination(CursorPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = ("shop_name", "id")


class RetailerListCreateView(RetailerView, generics.ListAPIView[Retailer]):
    serializer_class = s.RetailerListSerializer
    pagination_class = NamePagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[Retailer]:
        if getattr(self, "swagger_fake_view", False):
            return Retailer.objects.unscoped().none()
        f = s.RetailerFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        v = f.validated_data
        return selectors.retailers_for(
            _user(self.request),
            selectors.RetailerFilters(
                search=v["search"],
                status=v["status"],
                salesperson_id=v.get("salesperson"),
                state=v["state"],
                tag=v["tag"],
            ),
        )

    @extend_schema(
        parameters=[s.RetailerFilterSerializer], operation_id="retailers_list", tags=["retailers"]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.RetailerWriteSerializer,
        responses={201: s.RetailerDetailSerializer},
        operation_id="retailers_create",
        tags=["retailers"],
    )
    def post(self, request: Request) -> Response:
        data = s.RetailerWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        billing = v["billing_address"]
        retailer = services.create_retailer(
            shop_name=v["shop_name"],
            phone=v["mobile"],
            contact_name=v["owner_name"],
            email=v["email"],
            gstin=v["gstin"] or None,
            state_id=v["state_code"] or None,
            created_by=_user(request),
            billing=services.AddressInput(
                line1=billing["line1"],
                line2=billing["line2"],
                city=billing["city"],
                district=billing["district"],
                pincode=billing["pincode"],
                state_id=billing["state_code"],
            )
            if billing
            else None,
            extra={
                "salesperson_id": v["salesperson"],
                "notes": v["notes"],
                "tags": v["tags"],
                "preferred_language": v["preferred_language"],
            },
        )
        return Response(_detail(request, retailer.pk), status=201)


class RetailerDetailView(RetailerView):
    @extend_schema(
        responses=s.RetailerDetailSerializer, operation_id="retailers_retrieve", tags=["retailers"]
    )
    def get(self, request: Request, retailer_id: UUID) -> Response:
        return Response(_detail(request, retailer_id))

    @extend_schema(
        request=s.RetailerUpdateSerializer,
        responses=s.RetailerDetailSerializer,
        operation_id="retailers_update",
        tags=["retailers"],
    )
    def patch(self, request: Request, retailer_id: UUID) -> Response:
        _visible(request, retailer_id)
        data = s.RetailerUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changes = dict(data.validated_data)
        for api, field in (("state_code", "state_id"), ("salesperson", "salesperson_id")):
            if api in changes:
                changes[field] = changes.pop(api)
        if "gstin" in changes:
            changes["gstin"] = changes["gstin"] or None
        services.update_retailer(retailer_id, changes, by=_user(request))
        return Response(_detail(request, retailer_id))

    @extend_schema(
        request=None, responses={204: None}, operation_id="retailers_delete", tags=["retailers"]
    )
    def delete(self, request: Request, retailer_id: UUID) -> Response:
        _visible(request, retailer_id)
        services.delete_retailer(retailer_id, by=_user(request))
        return Response(status=204)


class RetailerCreditView(RetailerView):
    required_permissions = {"PATCH": "credit.manage"}

    @extend_schema(
        request=s.CreditSerializer,
        responses=s.RetailerDetailSerializer,
        operation_id="retailers_credit_update",
        tags=["retailers"],
    )
    def patch(self, request: Request, retailer_id: UUID) -> Response:
        _visible(request, retailer_id)
        data = s.CreditSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.update_credit(
            retailer_id,
            credit_limit=data.validated_data["credit_limit"],
            payment_terms_days=data.validated_data["payment_terms_days"],
            by=_user(request),
        )
        return Response(_detail(request, retailer_id))


class RetailerBlockView(RetailerView):
    @extend_schema(
        request=s.BlockSerializer,
        responses=s.RetailerDetailSerializer,
        operation_id="retailers_block",
        tags=["retailers"],
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        _visible(request, retailer_id)
        data = s.BlockSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.block_retailer(
            retailer_id, reason=data.validated_data["reason"], by=_user(request)
        )
        return Response(_detail(request, retailer_id))


class RetailerUnblockView(RetailerView):
    @extend_schema(
        request=None,
        responses=s.RetailerDetailSerializer,
        operation_id="retailers_unblock",
        tags=["retailers"],
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        _visible(request, retailer_id)
        services.unblock_retailer(retailer_id, by=_user(request))
        return Response(_detail(request, retailer_id))


class RetailerWelcomeView(RetailerView):
    @extend_schema(
        request=None,
        responses={202: None},
        operation_id="retailers_resend_welcome",
        tags=["retailers"],
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        _visible(request, retailer_id)
        services.resend_welcome(retailer_id, by=_user(request))
        return Response(status=202)


class AddressSaving(RetailerView):
    def _save(
        self, request: Request, retailer_id: UUID, address_id: UUID | None, status: int = 200
    ) -> Response:
        data = s.AddressWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        kind, is_default = v.pop("kind"), v.pop("is_default")
        v["state_id"] = v.pop("state_code")
        address = services.save_address(
            retailer_id, address_id, kind=kind, data=v, is_default=is_default, by=_user(request)
        )
        return Response(s.AddressSerializer(address).data, status=status)


class RetailerAddressesView(AddressSaving):
    @extend_schema(
        request=s.AddressWriteSerializer,
        responses={201: s.AddressSerializer},
        operation_id="retailers_addresses_create",
        tags=["retailers"],
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        _visible(request, retailer_id)
        return self._save(request, retailer_id, None, status=201)


class RetailerAddressDetailView(AddressSaving):
    @extend_schema(
        request=s.AddressWriteSerializer,
        responses=s.AddressSerializer,
        operation_id="retailers_addresses_update",
        tags=["retailers"],
    )
    def patch(self, request: Request, retailer_id: UUID, address_id: UUID) -> Response:
        _visible(request, retailer_id)
        return self._save(request, retailer_id, address_id)

    @extend_schema(
        request=None,
        responses={204: None},
        operation_id="retailers_addresses_delete",
        tags=["retailers"],
    )
    def delete(self, request: Request, retailer_id: UUID, address_id: UUID) -> Response:
        _visible(request, retailer_id)
        services.delete_address(retailer_id, address_id, by=_user(request))
        return Response(status=204)


class RetailerBulkView(RetailerView):
    @extend_schema(
        request=s.RetailerBulkSerializer,
        responses=s.RetailerBulkResultSerializer,
        operation_id="retailers_bulk",
        tags=["retailers"],
    )
    def post(self, request: Request) -> Response:
        data = s.RetailerBulkSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        visible = set(
            selectors.retailers_for(_user(request))
            .filter(pk__in=data.validated_data["retailer_ids"])
            .values_list("pk", flat=True)
        )
        changed = (
            services.bulk_update(
                list(visible),
                data.validated_data["action"],
                value=data.validated_data["value"],
                by=_user(request),
            )
            if visible
            else 0
        )
        return Response({"changed": changed})


class SalespeopleView(RetailerView):
    required_permissions = {"GET": MANAGE}

    @extend_schema(
        responses=s.SalespersonSerializer(many=True),
        operation_id="retailers_salespeople",
        tags=["retailers"],
    )
    def get(self, request: Request) -> Response:
        return Response(s.SalespersonSerializer(selectors.salespeople(), many=True).data)
