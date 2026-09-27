"""``POST auth/ws-ticket``: a one-time, 30-second ticket for the live-updates socket
(``common.live``). Staff get their tenant's order events if they may view orders; a shop login gets
its own shop's."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.retailers.selectors import own_retailer, sees_own_retailers_only
from common.live import TICKET_SECONDS, Grant, issue_ticket
from common.tenancy import get_current_tenant_id


class WsTicketSerializer(serializers.Serializer[Any]):
    ticket = serializers.CharField()
    expires_in = serializers.IntegerField(help_text="Seconds; the ticket works once.")


class WsTicketView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_ws_ticket", tags=["auth"], request=None, responses=WsTicketSerializer
    )
    def post(self, request: Request) -> Response:
        user: User = request.user  # type: ignore[assignment]
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise PermissionDenied()  # platform users have no live order feed
        if user.user_type == User.UserType.RETAILER:
            retailer = own_retailer(user)
            if retailer is None:
                raise PermissionDenied()
            grant = Grant(str(user.pk), str(tenant_id), retailer_id=str(retailer.pk))
        elif user.user_type == User.UserType.STAFF:
            grant = Grant(
                str(user.pk),
                str(tenant_id),
                orders=bool(user.has_permission_code("orders.view")),
                own_shops_only=sees_own_retailers_only(user),
            )
        else:
            raise PermissionDenied()
        body = {"ticket": issue_ticket(grant), "expires_in": TICKET_SECONDS}
        return Response(WsTicketSerializer(body).data)
