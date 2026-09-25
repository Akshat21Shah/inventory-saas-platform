"""Test-only API views used by common/ tests (mounted via common.tests.urls)."""

from typing import Any

from django.db import connection
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import DomainError
from common.idempotency import idempotent
from common.permissions import HasPermission
from common.tenancy import get_current_tenant_id
from common.tests.testapp.models import Widget

CALLS = {"count": 0}


class WhoAmIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.current_tenant', true)")
            db_tenant = cursor.fetchone()[0]
        tenant = get_current_tenant_id()
        return Response({"tenant": str(tenant) if tenant else None, "db_tenant": db_tenant or None})


class _Input(serializers.Serializer):  # type: ignore[type-arg]
    name = serializers.CharField(max_length=5)


class ErrorsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        mode = request.query_params.get("mode")
        Widget.objects.create(name="written")  # must be rolled back by every error path
        if mode == "domain":
            raise DomainError(
                "Credit limit exceeded.", code="CREDIT_LIMIT_EXCEEDED", details={"limit": "100.00"}
            )
        if mode == "validation":
            _Input(data=request.data).is_valid(raise_exception=True)
        if mode == "crash":
            raise RuntimeError("boom with secret internals")
        return Response({"ok": True}, status=201)


class IdempotentView(APIView):
    permission_classes = [IsAuthenticated]

    @idempotent("tests.create")
    def post(self, request: Request, **kwargs: Any) -> Response:
        CALLS["count"] += 1
        data = request.data if isinstance(request.data, dict) else {}
        if data.get("fail"):
            raise DomainError("nope")
        widget = Widget.objects.create(name=str(data.get("name", "w")))
        return Response({"id": str(widget.id), "call": CALLS["count"]}, status=201)


class GuardedView(APIView):
    permission_classes = [HasPermission]
    required_permission = "orders.accept"

    def get(self, request: Request) -> Response:
        return Response({"ok": True})


class PublicView(APIView):
    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"host_kind": request._request.host_context.kind})  # type: ignore[attr-defined]
