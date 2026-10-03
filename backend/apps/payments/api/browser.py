"""The app's browser payment page (ADR-061 item 9; owner, checkpoint review item 7): the link the
app opens, and the page's own endpoints. The page's session is a ``Pay`` token, which only these
endpoints read; every other endpoint ignores it."""

from typing import Any, cast
from uuid import UUID

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.payments import browser, online
from apps.payments.api import serializers as s
from apps.payments.models import PaymentIntent
from apps.shop.api.views import ShopView, _retailer
from common.errors import NotFound
from common.hosts import HostContext
from common.net import client_ip
from common.tenancy import tenant_context

PAY_TOKEN = OpenApiParameter(
    "Authorization", str, OpenApiParameter.HEADER, True, description="Pay <token>"
)


class ShopCheckoutBrowserView(ShopView):
    impersonation_blocked = True

    @extend_schema(
        operation_id="shop_checkout_browser",
        tags=["shop"],
        request=None,
        responses=s.BrowserPayLinkSerializer,
        description="The app pays in a Chrome Custom Tab: this checkout's payment page, opened "
        "once by a code that works for a minute. Back in the app, read the checkout's status here.",
    )
    def post(self, request: Request, intent_id: UUID) -> Response:
        intent = PaymentIntent.objects.filter(pk=intent_id, retailer=_retailer(request)).first()
        if intent is None:
            raise NotFound()
        url, expires_at = browser.browser_link(intent, cast(User, request.user))
        return Response(s.BrowserPayLinkSerializer({"url": url, "expires_at": expires_at}).data)


def _host(request: Request) -> HostContext:
    return cast(HostContext, request._request.host_context)  # type: ignore[attr-defined]


def _token(request: Request) -> str:
    scheme, _, raw = request.headers.get("Authorization", "").partition(" ")
    return raw.strip() if scheme == "Pay" else ""


def _describe(intent: PaymentIntent, page_open: bool) -> dict[str, Any]:
    with tenant_context(intent.tenant_id):
        return {
            **online.describe(intent),
            "page_open": page_open,
            "app_return_url": f"{settings.ANDROID_APP_SCHEME}://shop/payments/checkout/{intent.pk}",
        }


class PayView(APIView):
    """No shop session here, and the Pay token works nowhere else."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]


class PaySessionView(PayView):
    @extend_schema(
        operation_id="pay_session",
        tags=["pay"],
        request=s.PaySessionInputSerializer,
        responses=s.PaySessionSerializer,
    )
    def post(self, request: Request) -> Response:
        data = s.PaySessionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        token, row = browser.open_session(
            data.validated_data["code"], _host(request), client_ip(request._request)
        )
        body = {
            "token": token,
            "expires_at": row.expires_at,
            "checkout": _describe(row.intent, True),
        }
        return Response(s.PaySessionSerializer(body).data)


class PayCheckoutView(PayView):
    @extend_schema(
        operation_id="pay_checkout",
        tags=["pay"],
        parameters=[PAY_TOKEN],
        responses=s.PayCheckoutSerializer,
    )
    def get(self, request: Request) -> Response:
        intent, page_open = browser.session_checkout(_token(request), _host(request))
        return Response(s.PayCheckoutSerializer(_describe(intent, page_open)).data)


class PayCheckoutOutcomeView(PayView):
    @extend_schema(
        operation_id="pay_checkout_outcome",
        tags=["pay"],
        parameters=[PAY_TOKEN],
        request=s.CheckoutOutcomeSerializer,
        responses=s.PayCheckoutSerializer,
        description="What the page saw (informational: the payment counts only when the gateway "
        "confirms it).",
    )
    def post(self, request: Request) -> Response:
        data = s.CheckoutOutcomeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        intent = browser.note_session_outcome(
            _token(request), _host(request), data.validated_data["outcome"]
        )
        return Response(s.PayCheckoutSerializer(_describe(intent, True)).data)
