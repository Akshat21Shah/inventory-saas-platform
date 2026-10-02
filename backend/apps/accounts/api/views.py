"""Auth endpoints (PLAN §3.2). Thin: validate → service → response.

Login-flow endpoints are non-atomic: services manage their own transactions so that, for example,
a failed-attempt counter is committed even though the response is an error.
"""

from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import impersonation, retailer_login, services
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
from apps.retailers.models import RetailerUser
from common.authentication import (
    TENANT_CLAIM,
)
from common.context import request_meta_var
from common.errors import NotFound
from common.hosts import HostContext
from common.languages import all_languages
from common.permissions import IsStaffOrPlatformUser


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


def _login_response(outcome: services.LoginOutcome) -> Response:
    """Serialize any sign-in step; sets the refresh cookie when the step issued a session."""
    body: dict[str, Any] = {"status": outcome.status.value}
    if outcome.handoff is not None:
        body["handoff"] = {"code": outcome.handoff.code, "tenant_slug": outcome.handoff.tenant_slug}
    if outcome.choice_token is not None:
        body["choice_token"] = outcome.choice_token
        body["tenants"] = [{"id": t.pk, "name": t.name, "slug": t.slug} for t in outcome.tenants]
    if outcome.mfa_token is not None:
        body["mfa_token"] = outcome.mfa_token
    if outcome.enrolment_token is not None:
        body["enrolment_token"] = outcome.enrolment_token
    if outcome.recovery_codes:
        body["recovery_codes"] = outcome.recovery_codes
    if outcome.accounts:
        body["accounts"] = [
            {
                "choice_id": a.user.pk,
                "distributor_name": a.distributor_name,
                "shop_name": a.shop_name,
            }
            for a in outcome.accounts
        ]
    if outcome.tokens is not None:
        body.update(_token_body(outcome.tokens))
        body["user_type"] = outcome.user.user_type
    response = Response(s.LoginResponseSerializer(body).data)
    if outcome.tokens is not None and outcome.tokens.refresh:  # impersonation: no refresh
        set_refresh_cookie(response, outcome.tokens)
    return response


def _host(request: Request) -> HostContext:
    host: HostContext = request.host_context  # type: ignore[attr-defined]
    return host


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
        return _login_response(
            services.staff_login(
                data.validated_data["email"],
                data.validated_data["password"],
                _host(request),
                _client_ip(),
            )
        )


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
        return _login_response(
            services.exchange_handoff(data.validated_data["code"], _host(request), _client_ip())
        )


class StaffMfaVerifyView(PublicAuthView):
    @extend_schema(
        request=s.MfaVerifyInputSerializer,
        responses=s.LoginResponseSerializer,
        operation_id="auth_staff_mfa_verify",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.MfaVerifyInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return _login_response(
            services.verify_login_mfa(
                v["mfa_token"], v.get("code"), v.get("recovery_code"), _host(request), _client_ip()
            )
        )


class StaffMfaEnrolStartView(PublicAuthView):
    @extend_schema(
        request=s.EnrolmentTokenInputSerializer,
        responses=s.MfaSecretSerializer,
        operation_id="auth_staff_mfa_enrol_start",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.EnrolmentTokenInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        secret, uri = services.begin_enrolment(data.validated_data["enrolment_token"])
        return Response(s.MfaSecretSerializer({"secret": secret, "otpauth_uri": uri}).data)


class StaffMfaEnrolConfirmView(PublicAuthView):
    @extend_schema(
        request=s.EnrolmentConfirmInputSerializer,
        responses=s.LoginResponseSerializer,
        operation_id="auth_staff_mfa_enrol_confirm",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.EnrolmentConfirmInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return _login_response(
            services.confirm_enrolment(
                data.validated_data["enrolment_token"], data.validated_data["code"], _host(request)
            )
        )


class PasswordForgotView(PublicAuthView):
    @extend_schema(
        request=s.PasswordForgotInputSerializer,
        responses={202: None},
        operation_id="auth_password_forgot",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.PasswordForgotInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            services.request_password_reset(data.validated_data["email"], _client_ip())
        return Response(status=202)  # identical whether or not the account exists


class PasswordResetView(PublicAuthView):
    @extend_schema(
        request=s.PasswordResetInputSerializer,
        responses={204: None},
        operation_id="auth_password_reset",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.PasswordResetInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.reset_password(v["uid"], v["token"], v["new_password"])
        return Response(status=204)


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


class RetailerOtpRequestView(PublicAuthView):
    @extend_schema(
        request=s.RetailerOtpRequestInputSerializer,
        responses={202: s.RetailerOtpRequestResponseSerializer},
        operation_id="auth_retailer_otp_request",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.RetailerOtpRequestInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        retailer_login.request_otp(data.validated_data["phone"], _host(request), _client_ip())
        body = {
            "expires_in": settings.OTP_TTL_SECONDS,
            "resend_after": settings.OTP_RESEND_AFTER_SECONDS,
        }
        # Identical whether or not the number belongs to anyone (ADR-015).
        return Response(s.RetailerOtpRequestResponseSerializer(body).data, status=202)


class RetailerOtpVerifyView(PublicAuthView):
    @extend_schema(
        request=s.RetailerOtpVerifyInputSerializer,
        responses=s.LoginResponseSerializer,
        operation_id="auth_retailer_otp_verify",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.RetailerOtpVerifyInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return _login_response(
            retailer_login.verify_otp(
                data.validated_data["phone"],
                data.validated_data["code"],
                _host(request),
                _client_ip(),
            )
        )


class RetailerChooseAccountView(PublicAuthView):
    @extend_schema(
        request=s.RetailerChooseAccountInputSerializer,
        responses=s.LoginResponseSerializer,
        operation_id="auth_retailer_choose_account",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.RetailerChooseAccountInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        handoff = retailer_login.choose_account(
            data.validated_data["choice_token"], data.validated_data["choice_id"]
        )
        body = {
            "status": "handoff",
            "handoff": {"code": handoff.code, "tenant_slug": handoff.tenant_slug},
        }
        return Response(s.LoginResponseSerializer(body).data)


def _token_tenant_id(request: Request) -> UUID | None:
    token: Any = request.auth
    raw = token.get(TENANT_CLAIM) if token is not None else None
    return UUID(str(raw)) if raw else None


class MfaSetupView(APIView):
    permission_classes = [IsStaffOrPlatformUser]
    impersonation_blocked = True  # ADR-029: credentials never change in a support session

    @extend_schema(
        request=None,
        responses=s.MfaSetupResponseSerializer,
        operation_id="auth_mfa_setup",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        token, secret, uri = services.begin_mfa_setup(request.user)  # type: ignore[arg-type]
        body = {"setup_token": token, "secret": secret, "otpauth_uri": uri}
        return Response(s.MfaSetupResponseSerializer(body).data)


class MfaConfirmView(APIView):
    permission_classes = [IsStaffOrPlatformUser]
    impersonation_blocked = True  # ADR-029: credentials never change in a support session

    @extend_schema(
        request=s.MfaSetupConfirmInputSerializer,
        responses=s.RecoveryCodesSerializer,
        operation_id="auth_mfa_confirm",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.MfaSetupConfirmInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.limit_mfa_management(request.user)  # type: ignore[arg-type]
        codes = services.confirm_setup(
            data.validated_data["setup_token"], data.validated_data["code"]
        )
        return Response(s.RecoveryCodesSerializer({"recovery_codes": codes}).data)


class MfaDisableView(APIView):
    permission_classes = [IsStaffOrPlatformUser]
    impersonation_blocked = True  # ADR-029: credentials never change in a support session

    @extend_schema(
        request=s.PasswordAndFactorInputSerializer,
        responses={204: None},
        operation_id="auth_mfa_disable",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.PasswordAndFactorInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.limit_mfa_management(request.user)  # type: ignore[arg-type]
        services.disable_mfa(
            request.user,  # type: ignore[arg-type]
            v["password"],
            v.get("code"),
            v.get("recovery_code"),
            _token_tenant_id(request),
        )
        return Response(status=204)


class RecoveryCodesView(APIView):
    permission_classes = [IsStaffOrPlatformUser]
    impersonation_blocked = True  # ADR-029: credentials never change in a support session

    @extend_schema(
        request=s.PasswordAndFactorInputSerializer,
        responses=s.RecoveryCodesSerializer,
        operation_id="auth_mfa_recovery_codes",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.PasswordAndFactorInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.limit_mfa_management(request.user)  # type: ignore[arg-type]
        codes = services.regenerate_recovery_codes(
            request.user,  # type: ignore[arg-type]
            v["password"],
            v.get("code"),
            v.get("recovery_code"),
        )
        return Response(s.RecoveryCodesSerializer({"recovery_codes": codes}).data)


class PasswordChangeView(APIView):
    permission_classes = [IsStaffOrPlatformUser]
    impersonation_blocked = True  # ADR-029: credentials never change in a support session

    @extend_schema(
        request=s.PasswordChangeInputSerializer,
        responses=s.TokenResponseSerializer,
        operation_id="auth_password_change",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.PasswordChangeInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        tokens = services.change_password(
            request.user,  # type: ignore[arg-type]
            data.validated_data["current_password"],
            data.validated_data["new_password"],
            _token_tenant_id(request),
        )
        response = Response(s.TokenResponseSerializer(_token_body(tokens)).data)
        set_refresh_cookie(response, tokens)
        return response


class ImpersonationActView(APIView):
    """Switch the current support session to ACT mode (a reason is required; audited)."""

    permission_classes = [IsAuthenticated]
    impersonation_control = True

    @extend_schema(
        request=s.ImpersonationReasonSerializer,
        responses=s.TokenResponseSerializer,
        operation_id="auth_impersonation_act",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        session = _impersonation_session(request)
        data = s.ImpersonationReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        access, expires = impersonation.enable_act_mode(session, data.validated_data["reason"])
        return Response(
            s.TokenResponseSerializer({"access": access, "access_expires_at": expires}).data
        )


class ImpersonationEndView(APIView):
    permission_classes = [IsAuthenticated]
    impersonation_control = True

    @extend_schema(
        request=None, responses={204: None}, operation_id="auth_impersonation_end", tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        impersonation.end_impersonation(_impersonation_session(request))
        return Response(status=204)


def _impersonation_session(request: Request) -> Any:
    session = request.user.__dict__.get("impersonation_session")
    if session is None:
        raise NotFound()
    return session


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
        allowed = _languages_for(request)[0]
        services.update_profile(
            request.user,  # type: ignore[arg-type]
            **data.validated_data,
            allowed_languages=allowed,
        )
        return Response(s.MeSerializer(_me(request)).data)


def _languages_for(request: Request) -> tuple[tuple[str, ...], str]:
    """The languages this person may choose, and the one they see (ADR-060)."""
    from common import languages

    user: User = request.user  # type: ignore[assignment]
    token: Any = request.auth
    raw_tenant = token.get(TENANT_CLAIM) if token is not None else None
    tenant_id = UUID(str(raw_tenant)) if raw_tenant else None
    if user.user_type == User.UserType.PLATFORM:
        allowed = languages.codes()
        return allowed, languages.effective(user.preferred_language, allowed)
    allowed = languages.available_for_tenant(tenant_id)
    if user.user_type == User.UserType.RETAILER:
        link = RetailerUser.objects.filter(user=user).select_related("retailer").first()
        if link is not None:
            return allowed, languages.shop_language(link.retailer)
    return allowed, languages.effective(user.preferred_language, allowed)


def _me(request: Request) -> dict[str, Any]:
    user: User = request.user  # type: ignore[assignment]
    token: Any = request.auth
    raw_tenant = token.get(TENANT_CLAIM) if token is not None else None
    tenant_id = UUID(str(raw_tenant)) if raw_tenant else None
    info = tenant_info(tenant_id) if tenant_id else None
    membership = user.__dict__.get("membership")
    allowed, language = _languages_for(request)
    support_session = None
    session = user.__dict__.get("impersonation_session")
    if session is not None:
        support_session = {
            "session_id": session.pk,
            "impersonator_id": session.impersonator_id,
            "mode": session.mode,  # from the database: an ACT switch applies at once
            "expires_at": session.expires_at,
        }
    return {
        "id": user.pk,
        "user_type": user.user_type,
        "email": user.email,
        "phone": user.phone,
        "full_name": user.full_name,
        "preferred_language": user.preferred_language,
        "language": language,
        "languages": [
            {"code": row.code, "name": row.name, "native": row.native}
            for row in all_languages()
            if row.code in allowed
        ],
        "tenant": (
            {"id": info.id, "name": info.name, "slug": info.slug, "status": info.status}
            if info
            else None
        ),
        "role": (
            {"code": membership.role.code, "name": membership.role.name} if membership else None
        ),
        "retailer": _retailer_summary(user) if tenant_id else None,
        "permissions": sorted(user.permission_codes()),
        "features": effective_features(tenant_id) if tenant_id else {},
        "impersonation": support_session,
        "mfa_enabled": user.totp_enabled,
        "mfa_required": services.mfa_required_for(user, tenant_id),
    }


def _retailer_summary(user: User) -> dict[str, Any] | None:
    if user.user_type != User.UserType.RETAILER:
        return None
    link = RetailerUser.objects.filter(user=user).select_related("retailer").first()
    if link is None:
        return None
    retailer = link.retailer
    return {
        "id": retailer.pk,
        "shop_name": retailer.shop_name,
        "code": retailer.code,
        "on_hold": retailer.status == retailer.Status.BLOCKED,
    }
