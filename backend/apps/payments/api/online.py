"""Online payments (PLAN §3.10, ADR-049 items 9 and 10): the shop's checkout, the gateway's
webhook, the dev test-gateway page, and the office's view of checkouts and flagged payments."""

import html
from typing import Any, cast
from uuid import UUID

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.payments import gateway_config, online
from apps.payments.api import serializers as s
from apps.payments.api.serializers import PaymentDetailSerializer
from apps.payments.api.views import _uuid
from apps.payments.models import PaymentIntent
from apps.retailers.selectors import sees_own_retailers_only
from apps.shop.api.views import ShopView, _retailer
from common.errors import InvalidFields, NotFound
from common.hosts import HostKind
from common.idempotency import idempotent
from common.permissions import HasPermission
from common.tenancy import tenant_context

TAGS = ["payments"]


def _intents() -> Any:
    return PaymentIntent.objects.select_related("invoice", "payment", "retailer")


# --- The shop ----------------------------------------------------------------------------------


class ShopCheckoutView(ShopView):
    @extend_schema(
        operation_id="shop_checkout_start",
        tags=["shop"],
        request=s.CheckoutInputSerializer,
        responses=s.CheckoutSerializer,
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)],
    )
    @idempotent("shop.checkout")
    def post(self, request: Request) -> Response:
        data = s.CheckoutInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        intent = online.start_checkout(
            _retailer(request),
            purpose=v["purpose"],
            invoice_id=v["invoice_id"],
            amount=v["amount"],
            by=cast(User, request.user),
        )
        return Response(s.CheckoutSerializer(online.describe(_intents().get(pk=intent.pk))).data)


class ShopCheckoutDetailView(ShopView):
    def _intent(self, request: Request, intent_id: UUID) -> PaymentIntent:
        found: PaymentIntent | None = (
            _intents().filter(pk=intent_id, retailer=_retailer(request)).first()
        )
        if found is None:
            raise NotFound()
        return found

    @extend_schema(operation_id="shop_checkout", tags=["shop"], responses=s.CheckoutSerializer)
    def get(self, request: Request, intent_id: UUID) -> Response:
        return Response(
            s.CheckoutSerializer(online.describe(self._intent(request, intent_id))).data
        )

    @extend_schema(
        operation_id="shop_checkout_outcome",
        tags=["shop"],
        request=s.CheckoutOutcomeSerializer,
        responses=s.CheckoutSerializer,
        description="What the page saw (informational: the payment counts only when the gateway "
        "confirms it).",
    )
    def post(self, request: Request, intent_id: UUID) -> Response:
        data = s.CheckoutOutcomeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        intent = online.note_outcome(
            self._intent(request, intent_id), data.validated_data["outcome"]
        )
        return Response(s.CheckoutSerializer(online.describe(intent)).data)


# --- The gateway -------------------------------------------------------------------------------


class GatewayWebhookView(APIView):
    """Public: authenticated by the gateway's signature, with the distributor's webhook secret."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="payment_webhook",
        tags=["public"],
        request=None,
        responses={
            200: OpenApiResponse(description="Handled (or already handled)"),
            400: OpenApiResponse(description="The signature doesn't match"),
            404: OpenApiResponse(description="Unknown webhook address"),
        },
    )
    def post(self, request: Request, provider: str, token: str) -> HttpResponse:
        status, result = online.handle_webhook(provider, token, request.body, request.headers)
        return HttpResponse(result, status=status, content_type="text/plain")


# --- Dev: the test gateway's checkout page ----------------------------------------------------


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Test payment</title>
<style>body{{font-family:system-ui,sans-serif;max-width:28rem;margin:2rem auto;padding:0 1rem}}
button{{min-height:44px;padding:0 1.25rem;margin:.25rem .5rem .25rem 0;font-size:1rem}}
.note{{color:#555;font-size:.9rem}}</style></head><body>
<h1>Test payment</h1><p class="note">Development only: no money moves.</p>{body}</body></html>"""


class MockGatewayPageView(APIView):
    """DEV ONLY (the mock gateway): pay or fail a checkout; the signed webhook is then sent to
    this distributor's webhook exactly as a gateway would."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser]  # the page's own form

    def _find(self, request: Request, order_id: str) -> tuple[Any, PaymentIntent | None]:
        if not settings.ALLOW_MOCK_INTEGRATIONS:
            raise NotFound()
        from apps.platform.selectors import tenant_by_slug

        host = request._request.host_context  # type: ignore[attr-defined]
        tenant = tenant_by_slug(host.tenant_slug) if host.kind == HostKind.TENANT else None
        if tenant is None:
            raise NotFound()
        with tenant_context(tenant.pk):
            intent = _intents().filter(provider="MOCK", provider_order_id=order_id).first()
        return tenant, intent

    @extend_schema(exclude=True)
    def get(self, request: Request, order_id: str) -> HttpResponse:
        _tenant, intent = self._find(request, order_id)
        if intent is None:
            raise NotFound()
        body = (
            f"<p>{html.escape(intent.retailer.shop_name)} pays <b>₹{intent.amount:,.2f}</b>"
            f"{' for bill ' + html.escape(intent.invoice.number) if intent.invoice else ''}.</p>"
            '<form method="post"><button name="outcome" value="CAPTURED">Pay</button>'
            '<button name="outcome" value="FAILED">Fail</button></form>'
        )
        return HttpResponse(PAGE.format(body=body))

    @extend_schema(exclude=True)
    def post(self, request: Request, order_id: str) -> HttpResponse:
        from apps.payments.gateway.mock import MockGateway

        tenant, intent = self._find(request, order_id)
        if intent is None:
            raise NotFound()
        outcome = "CAPTURED" if request.POST.get("outcome") == "CAPTURED" else "FAILED"
        with tenant_context(tenant.pk):
            keys = gateway_config.keys_of(gateway_config.current())  # type: ignore[arg-type]
        payload, headers = MockGateway.simulate(keys, order_id, outcome=outcome)
        status, _result = online.handle_webhook("mock", tenant.webhook_token, payload, headers)
        text = "Paid. Go back to the app." if outcome == "CAPTURED" else "The payment failed."
        # The shop's checkout page, or the Android app's browser payment page (ADR-061 item 9).
        page = "pay" if request.query_params.get("back") == "pay" else "shop/payments/checkout"
        back = f'<p><a href="/{page}/{intent.pk}">Back to the app</a></p>'
        return HttpResponse(PAGE.format(body=f"<p>{text}</p>{back}"), status=status)


# --- The office ---------------------------------------------------------------------------------


class Newest(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("-created_at", "-id")


class PaymentIntentListView(generics.ListAPIView[PaymentIntent]):
    permission_classes = [HasPermission]
    required_permission = "payments.view"
    serializer_class = s.PaymentIntentRowSerializer
    pagination_class = Newest

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return PaymentIntent.objects.none()
        q = self.request.query_params
        user = cast(User, self.request.user)
        rows = _intents()
        if sees_own_retailers_only(user):
            rows = rows.filter(retailer__salesperson=user)
        status = q.get("status", "")
        if status and status not in PaymentIntent.Status.values:
            raise InvalidFields({"status": [_("Not a valid value.")]})
        if status:
            rows = rows.filter(status=status)
        retailer = _uuid(q.get("retailer"), "retailer")
        if retailer:
            rows = rows.filter(retailer_id=retailer)
        term = q.get("search", "").strip()
        if term:
            rows = rows.filter(
                Q(retailer__shop_name__icontains=term)
                | Q(retailer__code__iexact=term)
                | Q(invoice__number__icontains=term)
                | Q(payment__number__icontains=term)
                | Q(provider_order_id=term)
            )
        return rows

    def paginate_queryset(self, queryset: Any) -> Any:
        page = super().paginate_queryset(queryset)
        return [online.describe(r) for r in page] if page is not None else None

    @extend_schema(
        operation_id="payment_intents_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("status", str, enum=list(PaymentIntent.Status.values)),
            OpenApiParameter("retailer", UUID),
            OpenApiParameter("search", str, description="Shop, bill, receipt or gateway order"),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class PaymentReviewView(APIView):
    permission_classes = [HasPermission]
    required_permission = "payments.record"

    @extend_schema(
        operation_id="payment_review",
        tags=TAGS,
        request=s.ReviewSerializer,
        responses=PaymentDetailSerializer,
    )
    def post(self, request: Request, payment_id: UUID) -> Response:
        data = s.ReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        online.mark_reviewed(
            payment_id, note=data.validated_data["note"], by=cast(User, request.user)
        )
        from apps.payments import selectors

        found = selectors.payment_detail(payment_id, user=cast(User, request.user))
        return Response(PaymentDetailSerializer(found).data)
