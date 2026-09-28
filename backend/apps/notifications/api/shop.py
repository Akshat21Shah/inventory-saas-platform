"""The shop's notification APIs (PLAN §3.11): its inbox, preferences, WhatsApp consent and the
distributor's announcements. Only RETAILER logins; everything is the login's own."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications import announcements, consent, preferences, selectors
from apps.notifications.api import serializers as s
from apps.notifications.api.views import Newest, _user, consent_state
from apps.notifications.models import Notification
from apps.retailers.models import Retailer
from apps.shop.api.views import _retailer
from common.errors import NotFound
from common.permissions import IsRetailer

TAGS = ["shop"]


class ShopInboxView(generics.ListAPIView[Notification]):
    permission_classes = [IsRetailer]
    serializer_class = s.InboxItemSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Notification]:
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.unscoped().none()
        _retailer(self.request)
        rows = selectors.inbox(_user(self.request))
        if self.request.query_params.get("unread") == "true":
            rows = rows.filter(read_at__isnull=True)
        return rows

    @extend_schema(
        operation_id="shop_notifications",
        tags=TAGS,
        parameters=[OpenApiParameter("unread", bool, required=False)],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class ShopUnreadCountView(APIView):
    permission_classes = [IsRetailer]

    @extend_schema(
        operation_id="shop_notifications_unread_count", tags=TAGS, responses=s.UnreadCountSerializer
    )
    def get(self, request: Request) -> Response:
        _retailer(request)
        return Response({"unread": selectors.unread_count(_user(request))})


class ShopMarkReadView(APIView):
    permission_classes = [IsRetailer]

    @extend_schema(
        operation_id="shop_notifications_mark_read",
        tags=TAGS,
        request=None,
        responses=s.MarkedReadSerializer,
    )
    def post(self, request: Request, notification_id: UUID) -> Response:
        _retailer(request)
        if not selectors.inbox(_user(request)).filter(pk=notification_id).exists():
            raise NotFound()
        return Response({"marked": selectors.mark_read(_user(request), notification_id)})


class ShopMarkAllReadView(APIView):
    permission_classes = [IsRetailer]

    @extend_schema(
        operation_id="shop_notifications_mark_all_read",
        tags=TAGS,
        request=None,
        responses=s.MarkedReadSerializer,
    )
    def post(self, request: Request) -> Response:
        _retailer(request)
        return Response({"marked": selectors.mark_read(_user(request))})


class ShopPreferencesView(APIView):
    permission_classes = [IsRetailer]

    @extend_schema(
        operation_id="shop_notification_preferences",
        tags=TAGS,
        responses=s.PreferenceRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        _retailer(request)
        rows = preferences.settings_for(_user(request), shop=True)
        return Response(s.PreferenceRowSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="shop_notification_preferences_update",
        tags=TAGS,
        request=s.PreferenceInputSerializer,
        responses=s.PreferenceRowSerializer(many=True),
    )
    def put(self, request: Request) -> Response:
        _retailer(request)
        data = s.PreferenceInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        preferences.set_preference(
            _user(request), v["event"], v["channel"], v["enabled"], shop=True
        )
        return self.get(request)


class ShopConsentView(APIView):
    permission_classes = [IsRetailer]

    @extend_schema(
        operation_id="shop_whatsapp_consent", tags=TAGS, responses=s.ConsentStateSerializer
    )
    def get(self, request: Request) -> Response:
        return Response(s.ConsentStateSerializer(consent_state(_retailer(request))).data)

    @extend_schema(
        operation_id="shop_whatsapp_consent_update",
        tags=TAGS,
        request=s.ShopConsentInputSerializer,
        responses=s.ConsentStateSerializer,
    )
    def put(self, request: Request) -> Response:
        shop = _retailer(request)
        data = s.ShopConsentInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        updated = consent.set_whatsapp_consent(
            shop.pk,
            data.validated_data["agreed"],
            source=consent.Source.SHOP_APP,
            by=_user(request),
        )
        consent.mark_prompted(shop.pk)
        updated.refresh_from_db()
        return Response(s.ConsentStateSerializer(consent_state(updated)).data)


class ShopConsentPromptedView(APIView):
    permission_classes = [IsRetailer]

    @extend_schema(
        operation_id="shop_whatsapp_consent_prompted",
        tags=TAGS,
        request=None,
        responses=s.ConsentStateSerializer,
    )
    def post(self, request: Request) -> Response:
        """The one-time question was shown and closed without an answer: don't ask again."""
        shop = _retailer(request)
        consent.mark_prompted(shop.pk)
        return Response(
            s.ConsentStateSerializer(consent_state(Retailer.objects.get(pk=shop.pk))).data
        )


class ShopAnnouncementsView(APIView):
    permission_classes = [IsRetailer]

    @extend_schema(
        operation_id="shop_announcements",
        tags=TAGS,
        responses=s.ShopAnnouncementSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        _retailer(request)
        rows = announcements.showing().order_by("-starts_at")[:10]
        return Response(s.ShopAnnouncementSerializer(rows, many=True).data)
