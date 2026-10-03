"""Staff management (tenant, ``staff.manage``) and invitation acceptance (public, PLAN §3.4).

Staff management is always blocked during impersonation (ADR-029): ``impersonation_blocked``.
"""

from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import selectors, staff_services
from apps.accounts.api import staff_serializers as s
from apps.accounts.api.serializers import LoginResponseSerializer
from apps.accounts.api.views import PublicAuthView, _host, _login_response
from apps.accounts.models import Invitation, Membership, Permission, Role, User
from common.errors import NotFound
from common.permissions import HasPermission


class StaffManageView(APIView):
    permission_classes = [HasPermission]
    required_permission = "staff.manage"
    impersonation_blocked = True


class StaffListView(StaffManageView, generics.ListAPIView[Membership]):
    serializer_class = s.MembershipSerializer

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):  # schema generation: no tenant is active
            return Membership.objects.unscoped().none()
        return selectors.staff_members()

    @extend_schema(operation_id="staff_list", tags=["staff"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class StaffDetailView(StaffManageView):
    def _member(self, membership_id: UUID) -> Membership:
        member = selectors.staff_member(membership_id)
        if member is None:
            raise NotFound()
        return member

    @extend_schema(responses=s.MembershipSerializer, operation_id="staff_retrieve", tags=["staff"])
    def get(self, request: Request, membership_id: UUID) -> Response:
        return Response(s.MembershipSerializer(self._member(membership_id)).data)

    @extend_schema(
        request=s.MembershipUpdateSerializer,
        responses=s.MembershipSerializer,
        operation_id="staff_update",
        tags=["staff"],
    )
    def patch(self, request: Request, membership_id: UUID) -> Response:
        data = s.MembershipUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user: User = request.user  # type: ignore[assignment]
        staff_services.change_member(
            membership_id,
            by=user,
            role_code=data.validated_data.get("role_code"),
            is_active=data.validated_data.get("is_active"),
        )
        return Response(s.MembershipSerializer(self._member(membership_id)).data)


class InvitationListCreateView(StaffManageView, generics.ListAPIView[Invitation]):
    serializer_class = s.InvitationSerializer

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return Invitation.objects.unscoped().none()
        return selectors.invitations()

    @extend_schema(operation_id="staff_invitations_list", tags=["staff"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.InvitationCreateSerializer,
        responses={201: s.InvitationSerializer},
        operation_id="staff_invitations_create",
        tags=["staff"],
    )
    def post(self, request: Request) -> Response:
        data = s.InvitationCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invitation = staff_services.invite_staff(
            email=data.validated_data["email"],
            role_code=data.validated_data["role_code"],
            invited_by=request.user,  # type: ignore[arg-type]
            language=data.validated_data.get("language", ""),
        )
        return Response(s.InvitationSerializer(invitation).data, status=201)


class InvitationResendView(StaffManageView):
    @extend_schema(
        request=None,
        responses=s.InvitationSerializer,
        operation_id="staff_invitations_resend",
        tags=["staff"],
    )
    def post(self, request: Request, invitation_id: UUID) -> Response:
        invitation = staff_services.resend_invitation(invitation_id, by=request.user)  # type: ignore[arg-type]
        return Response(s.InvitationSerializer(invitation).data)


class InvitationRevokeView(StaffManageView):
    @extend_schema(
        request=None,
        responses=s.InvitationSerializer,
        operation_id="staff_invitations_revoke",
        tags=["staff"],
    )
    def post(self, request: Request, invitation_id: UUID) -> Response:
        invitation = staff_services.revoke_invitation(invitation_id, by=request.user)  # type: ignore[arg-type]
        return Response(s.InvitationSerializer(invitation).data)


class RoleListView(StaffManageView, generics.ListAPIView[Role]):
    serializer_class = s.RoleSerializer
    pagination_class = None  # a short, fixed catalogue

    def get_queryset(self) -> Any:
        return selectors.tenant_roles()

    @extend_schema(operation_id="roles_list", tags=["staff"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class PermissionListView(StaffManageView, generics.ListAPIView[Permission]):
    serializer_class = s.PermissionSerializer
    pagination_class = None

    def get_queryset(self) -> Any:
        return Permission.objects.exclude(code__startswith="platform.").order_by("code")

    @extend_schema(operation_id="permissions_list", tags=["staff"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


# --- Invitation acceptance (public; the link is on the tenant's subdomain) ----------------------


class InvitationPreviewView(PublicAuthView):
    @extend_schema(
        request=s.InvitationTokenSerializer,
        responses=s.InvitationPreviewSerializer,
        operation_id="auth_invitation_preview",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.InvitationTokenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        preview = staff_services.preview_invitation(data.validated_data["token"], _host(request))
        return Response(s.InvitationPreviewSerializer(preview).data)


class InvitationAcceptView(PublicAuthView):
    @extend_schema(
        request=s.InvitationAcceptSerializer,
        responses=LoginResponseSerializer,
        operation_id="auth_invitation_accept",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = s.InvitationAcceptSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return _login_response(
            staff_services.accept_invitation(
                v["token"],
                _host(request),
                full_name=v.get("full_name", ""),
                password=v["password"],
                language=v.get("language", ""),
            )
        )
