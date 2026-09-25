"""Auth endpoints (PLAN §3.2). Thin: validate → service → response.

Login-flow endpoints are non-atomic: services manage their own transactions so that, for example,
a failed-attempt counter is committed even though the response is an error.
"""

from typing import Any
from uuid import UUID

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.api import serializers as s
from apps.accounts.api.cookies import (
    clear_refresh_cookie,
    read_refresh_cookie,
    require_same_origin,
    set_refresh_cookie,
)
from apps.accounts.models import User
from apps.accounts.tokens import IssuedTokens, SessionExpired
from apps.platform.selectors import effective_features, tenant_info
from common.authentication import (
    IMPERSONATION_MODE_CLAIM,
    IMPERSONATION_SESSION_CLAIM,
    IMPERSONATOR_CLAIM,
    TENANT_CLAIM,
)
from common.context import request_meta_var


def _client_ip() -> str | None:
    meta = request_meta_var.get()
    return meta.ip if meta else None


def _token_body(tokens: IssuedTokens) -> dict[str, Any]:
    return {"access": tokens.access, "access_expires_at": tokens.access_expires_at}


class PublicAuthView(APIView):
    """No authentication, any caller; and no request-wide transaction (see module docstring)."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    atomic_request = False  # read by the exception handler

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        return transaction.non_atomic_requests(super().as_view(**initkwargs))


class StaffLoginView(PublicAuthView):
    @extend_schema(
        request=s.StaffLoginInputSerializer,
        responses=s.LoginResponseSerializer,
        operation_id="auth_staff_login",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.StaffLoginInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        outcome = services.staff_login(
            data.validated_data["email"],
            data.validated_data["password"],
            request.host_context,  # type: ignore[attr-defined]
            _client_ip(),
        )
        body: dict[str, Any] = {"status": outcome.status.value}
        if outcome.handoff is not None:
            body["handoff"] = {
                "code": outcome.handoff.code,
                "tenant_slug": outcome.handoff.tenant_slug,
            }
        if outcome.choice_token is not None:
            body["choice_token"] = outcome.choice_token
            body["tenants"] = [
                {"id": t.pk, "name": t.name, "slug": t.slug} for t in outcome.tenants
            ]
        if outcome.tokens is not None:
            body.update(_token_body(outcome.tokens))
        response = Response(s.LoginResponseSerializer(body).data)
        if outcome.tokens is not None:
            set_refresh_cookie(response, outcome.tokens)
        return response


class ChooseTenantView(PublicAuthView):
    @extend_schema(
        request=s.ChooseTenantInputSerializer,
        responses=s.LoginResponseSerializer,
        operation_id="auth_staff_choose_tenant",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.ChooseTenantInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        handoff = services.choose_tenant(
            data.validated_data["choice_token"], data.validated_data["tenant_id"]
        )
        body = {
            "status": "handoff",
            "handoff": {"code": handoff.code, "tenant_slug": handoff.tenant_slug},
        }
        return Response(s.LoginResponseSerializer(body).data)


class HandoffExchangeView(PublicAuthView):
    @extend_schema(
        request=s.HandoffExchangeInputSerializer,
        responses=s.LoginResponseSerializer,
        operation_id="auth_handoff_exchange",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        require_same_origin(request)  # it sets a cookie for this host
        data = s.HandoffExchangeInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        outcome = services.exchange_handoff(
            data.validated_data["code"],
            request.host_context,  # type: ignore[attr-defined]
            _client_ip(),
        )
        assert outcome.tokens is not None
        response = Response(
            s.LoginResponseSerializer(
                {"status": "authenticated", **_token_body(outcome.tokens)}
            ).data
        )
        set_refresh_cookie(response, outcome.tokens)
        return response


class TokenRefreshView(PublicAuthView):
    @extend_schema(
        request=s.RefreshInputSerializer,
        responses=s.TokenResponseSerializer,
        operation_id="auth_token_refresh",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.RefreshInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        from_body = data.validated_data.get("refresh")
        raw = from_body or read_refresh_cookie(request)
        if not from_body:
            require_same_origin(request)
        if not raw:
            raise SessionExpired()
        _, tokens = services.refresh_session(raw)
        body = _token_body(tokens)
        if from_body:
            body["refresh"] = tokens.refresh  # mobile clients keep the refresh token themselves
            return Response(s.TokenResponseSerializer(body).data)
        response = Response(s.TokenResponseSerializer(body).data)
        set_refresh_cookie(response, tokens)
        return response


class LogoutView(PublicAuthView):
    @extend_schema(
        request=s.RefreshInputSerializer,
        responses={204: None},
        operation_id="auth_logout",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.RefreshInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        from_body = data.validated_data.get("refresh")
        if not from_body:
            require_same_origin(request)
        services.logout(from_body or read_refresh_cookie(request))
        response = Response(status=204)
        clear_refresh_cookie(response)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=s.MeSerializer, operation_id="auth_me_retrieve", tags=["auth"])
    def get(self, request: Request) -> Response:
        return Response(s.MeSerializer(_me(request)).data)

    @extend_schema(
        request=s.MeUpdateSerializer,
        responses=s.MeSerializer,
        operation_id="auth_me_update",
        tags=["auth"],
    )
    def patch(self, request: Request) -> Response:
        data = s.MeUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_profile(request.user, **data.validated_data)  # type: ignore[arg-type]
        return Response(s.MeSerializer(_me(request)).data)


def _me(request: Request) -> dict[str, Any]:
    user: User = request.user  # type: ignore[assignment]
    token: Any = request.auth
    raw_tenant = token.get(TENANT_CLAIM) if token is not None else None
    tenant_id = UUID(str(raw_tenant)) if raw_tenant else None
    info = tenant_info(tenant_id) if tenant_id else None
    membership = user.__dict__.get("membership")
    impersonation = None
    if token is not None and token.get(IMPERSONATION_SESSION_CLAIM):
        impersonation = {
            "session_id": token.get(IMPERSONATION_SESSION_CLAIM),
            "impersonator_id": token.get(IMPERSONATOR_CLAIM),
            "mode": token.get(IMPERSONATION_MODE_CLAIM, "READ_ONLY"),
        }
    return {
        "id": user.pk,
        "user_type": user.user_type,
        "email": user.email,
        "phone": user.phone,
        "full_name": user.full_name,
        "preferred_language": user.preferred_language,
        "tenant": (
            {"id": info.id, "name": info.name, "slug": info.slug, "status": info.status}
            if info
            else None
        ),
        "role": (
            {"code": membership.role.code, "name": membership.role.name} if membership else None
        ),
        "permissions": sorted(user.permission_codes()),
        "features": effective_features(tenant_id) if tenant_id else {},
        "impersonation": impersonation,
    }
