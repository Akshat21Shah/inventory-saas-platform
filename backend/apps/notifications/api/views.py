"""Staff notification APIs (PLAN §3.11). Thin: permission → serializer → service/selector."""

from datetime import date
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.audit import services as audit
from apps.notifications import (
    announcements,
    consent,
    delivery,
    jobs,
    links,
    preferences,
    rules,
    selectors,
    texts,
)
from apps.notifications.api import serializers as s
from apps.notifications.models import Announcement, Channel, Notification
from apps.retailers.selectors import retailer_for
from common.dates import today_ist
from common.errors import InvalidFields, NotFound
from common.permissions import AnyOf, HasPermission, IsTenantStaff

MANAGE = "notifications.manage"
TAGS = ["notifications"]


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


class Guarded(APIView):
    permission_classes = [HasPermission]


class Newest(CursorPagination):
    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = ("-created_at", "-id")


# --- Inbox (own) ------------------------------------------------------------------------------


class InboxView(generics.ListAPIView[Notification]):
    permission_classes = [IsTenantStaff]
    serializer_class = s.InboxItemSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Notification]:
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.unscoped().none()
        rows = selectors.inbox(_user(self.request))
        if self.request.query_params.get("unread") == "true":
            rows = rows.filter(read_at__isnull=True)
        return rows

    @extend_schema(
        operation_id="notifications_inbox",
        tags=TAGS,
        parameters=[OpenApiParameter("unread", bool, required=False)],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class UnreadCountView(APIView):
    permission_classes = [IsTenantStaff]

    @extend_schema(
        operation_id="notifications_unread_count", tags=TAGS, responses=s.UnreadCountSerializer
    )
    def get(self, request: Request) -> Response:
        return Response({"unread": selectors.unread_count(_user(request))})


class MarkReadView(APIView):
    permission_classes = [IsTenantStaff]

    @extend_schema(
        operation_id="notifications_mark_read",
        tags=TAGS,
        request=None,
        responses=s.MarkedReadSerializer,
    )
    def post(self, request: Request, notification_id: UUID) -> Response:
        if not selectors.inbox(_user(request)).filter(pk=notification_id).exists():
            raise NotFound()
        return Response({"marked": selectors.mark_read(_user(request), notification_id)})


class MarkAllReadView(APIView):
    permission_classes = [IsTenantStaff]

    @extend_schema(
        operation_id="notifications_mark_all_read",
        tags=TAGS,
        request=None,
        responses=s.MarkedReadSerializer,
    )
    def post(self, request: Request) -> Response:
        return Response({"marked": selectors.mark_read(_user(request))})


class StaffPreferencesView(APIView):
    permission_classes = [IsTenantStaff]

    @extend_schema(
        operation_id="notification_preferences",
        tags=TAGS,
        responses=s.PreferenceRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        rows = preferences.settings_for(_user(request), shop=False)
        return Response(s.PreferenceRowSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="notification_preferences_update",
        tags=TAGS,
        request=s.PreferenceInputSerializer,
        responses=s.PreferenceRowSerializer(many=True),
    )
    def put(self, request: Request) -> Response:
        data = s.PreferenceInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        preferences.set_preference(
            _user(request), v["event"], v["channel"], v["enabled"], shop=False
        )
        return self.get(request)


# --- Rules --------------------------------------------------------------------------------------


class RulesView(Guarded):
    required_permission = MANAGE

    @extend_schema(operation_id="notification_rules", tags=TAGS, responses=s.RulesMatrixSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.RulesMatrixSerializer(selectors.rules_matrix()).data)


class EventRulesView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="notification_rules_update",
        tags=TAGS,
        request=s.RulesUpdateSerializer,
        responses=s.RuleSerializer(many=True),
    )
    def put(self, request: Request, event: str) -> Response:
        data = s.RulesUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        given = [
            rules.RuleInput(
                r["recipient"], tuple(r["channels"]), r["permission"], r["enabled"], r["compulsory"]
            )
            for r in data.validated_data["rules"]
        ]
        saved = rules.save_rules(event, given)
        return Response(s.RuleSerializer([_rule(r) for r in saved], many=True).data)

    @extend_schema(
        operation_id="notification_rules_reset",
        tags=TAGS,
        responses={200: s.RuleSerializer(many=True)},
    )
    def delete(self, request: Request, event: str) -> Response:
        saved = rules.reset_rules(event)
        return Response(s.RuleSerializer([_rule(r) for r in saved], many=True).data)


def _rule(rule: rules.EffectiveRule) -> dict[str, Any]:
    return {
        "recipient": rule.recipient,
        "permission": rule.permission,
        "channels": list(rule.channels),
        "enabled": rule.enabled,
        "compulsory": rule.compulsory,
        "is_default": rule.is_default,
    }


# --- Texts --------------------------------------------------------------------------------------

LOCALE = OpenApiParameter("locale", str, required=False, enum=list(texts.LOCALES))


def _locale(request: Request) -> str:
    locale = request.query_params.get("locale", "en")
    if locale not in texts.LOCALES:
        raise InvalidFields({"locale": ["Choose en, hi or mr."]})
    return locale


class EventTextsView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="notification_texts",
        tags=TAGS,
        parameters=[LOCALE],
        responses=s.TextSerializer(many=True),
    )
    def get(self, request: Request, event: str) -> Response:
        return Response(s.TextSerializer(texts.texts_for(event, _locale(request)), many=True).data)


class EventTextView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="notification_text_update",
        tags=TAGS,
        request=s.TextInputSerializer,
        responses=s.TextSerializer(many=True),
    )
    def put(self, request: Request, event: str, channel: str) -> Response:
        data = s.TextInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        texts.save_tenant_text(
            texts.TextInput(event, channel, v["locale"], v["subject"], v["body"])
        )
        return Response(s.TextSerializer(texts.texts_for(event, v["locale"]), many=True).data)

    @extend_schema(
        operation_id="notification_text_reset",
        tags=TAGS,
        parameters=[LOCALE],
        responses={200: s.TextSerializer(many=True)},
    )
    def delete(self, request: Request, event: str, channel: str) -> Response:
        locale = _locale(request)
        texts.reset_tenant_text(event, channel, locale)
        return Response(s.TextSerializer(texts.texts_for(event, locale), many=True).data)


class TextPreviewView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="notification_text_preview",
        tags=TAGS,
        request=s.TextPreviewInputSerializer,
        responses=s.TextPreviewSerializer,
    )
    def post(self, request: Request) -> Response:
        from apps.notifications.context import current_tenant, distributor_name

        data = s.TextPreviewInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        shown = texts.preview(
            texts.TextInput(v["event"], v["channel"], v["locale"], v["subject"], v["body"]),
            distributor_name(current_tenant()),
        )
        return Response(s.TextPreviewSerializer(shown).data)


# --- Delivery log -------------------------------------------------------------------------------


def _date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidFields({field: ["Use YYYY-MM-DD."]}) from exc


def _uuid(value: str | None, field: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise InvalidFields({field: ["Not a valid id."]}) from exc


class DeliveriesView(Guarded, generics.ListAPIView[Notification]):
    required_permission = MANAGE
    serializer_class = s.DeliveryRowSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Notification]:
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.unscoped().none()
        q = self.request.query_params
        for field, allowed in (("status", Notification.Status.values), ("channel", Channel.values)):
            if q.get(field) and q[field] not in allowed:
                raise InvalidFields({field: ["Not a valid value."]})
        return selectors.deliveries(
            selectors.DeliveryFilters(
                status=q.get("status", ""),
                channel=q.get("channel", ""),
                event=q.get("event", ""),
                retailer_id=_uuid(q.get("retailer"), "retailer"),
                date_from=_date(q.get("date_from"), "date_from"),
                date_to=_date(q.get("date_to"), "date_to"),
                search=q.get("search", ""),
            )
        )

    @extend_schema(
        operation_id="notification_deliveries",
        tags=TAGS,
        parameters=[
            OpenApiParameter("status", str, enum=Notification.Status.values, required=False),
            OpenApiParameter("channel", str, enum=Channel.values, required=False),
            OpenApiParameter("event", str, required=False),
            OpenApiParameter("retailer", str, required=False),
            OpenApiParameter("date_from", str, required=False),
            OpenApiParameter("date_to", str, required=False),
            OpenApiParameter("search", str, required=False),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class DeliveryCountsView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="notification_delivery_counts", tags=TAGS, responses=s.DeliveryCountsSerializer
    )
    def get(self, request: Request) -> Response:
        return Response(s.DeliveryCountsSerializer(selectors.delivery_counts()).data)


def _delivery(notification_id: UUID) -> Notification:
    found: Notification | None = (
        Notification.objects.select_related("recipient", "retailer")
        .prefetch_related("delivery_attempts")
        .filter(pk=notification_id)
        .first()
    )
    if found is None:
        raise NotFound()
    return found


class DeliveryDetailView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="notification_delivery", tags=TAGS, responses=s.DeliveryDetailSerializer
    )
    def get(self, request: Request, notification_id: UUID) -> Response:
        return Response(s.DeliveryDetailSerializer(_delivery(notification_id)).data)


class DeliveryRetryView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="notification_delivery_retry",
        tags=TAGS,
        request=None,
        responses=s.DeliveryDetailSerializer,
    )
    def post(self, request: Request, notification_id: UUID) -> Response:
        row = _delivery(notification_id)
        if not delivery.retry(row.pk):
            raise InvalidFields({"status": ["Only a failed message can be tried again."]})
        audit.record(
            "notifications.delivery_retried",
            target=row,
            target_repr=f"{row.event_code} {row.channel}",
        )
        return Response(s.DeliveryDetailSerializer(_delivery(notification_id)).data)


# --- Announcements ------------------------------------------------------------------------------


def _announcement_input(data: dict[str, Any]) -> announcements.AnnouncementInput:
    return announcements.AnnouncementInput(
        data["title"],
        data["body"],
        data["starts_at"],
        data.get("ends_at"),
        data.get("is_active", True),
        data.get("send_whatsapp", False),
    )


class AnnouncementsView(Guarded, generics.ListAPIView[Announcement]):
    required_permission = MANAGE
    serializer_class = s.AnnouncementSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Announcement]:
        if getattr(self, "swagger_fake_view", False):
            return Announcement.objects.unscoped().none()
        return Announcement.objects.all()

    @extend_schema(operation_id="announcements", tags=TAGS)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="announcement_create",
        tags=TAGS,
        request=s.AnnouncementSerializer,
        responses={201: s.AnnouncementSerializer},
    )
    def post(self, request: Request) -> Response:
        data = s.AnnouncementSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = announcements.save(_announcement_input(data.validated_data), by=_user(request))
        return Response(s.AnnouncementSerializer(row).data, status=201)


class AnnouncementDetailView(Guarded):
    required_permission = MANAGE

    def _row(self, announcement_id: UUID) -> Announcement:
        found: Announcement | None = Announcement.objects.filter(pk=announcement_id).first()
        if found is None:
            raise NotFound()
        return found

    @extend_schema(operation_id="announcement", tags=TAGS, responses=s.AnnouncementSerializer)
    def get(self, request: Request, announcement_id: UUID) -> Response:
        return Response(s.AnnouncementSerializer(self._row(announcement_id)).data)

    @extend_schema(
        operation_id="announcement_update",
        tags=TAGS,
        request=s.AnnouncementSerializer,
        responses=s.AnnouncementSerializer,
    )
    def put(self, request: Request, announcement_id: UUID) -> Response:
        self._row(announcement_id)
        data = s.AnnouncementSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = announcements.save(
            _announcement_input(data.validated_data),
            by=_user(request),
            announcement_id=announcement_id,
        )
        return Response(s.AnnouncementSerializer(row).data)


# --- Document links -----------------------------------------------------------------------------

LINK_PERMISSIONS = AnyOf(("invoices.manage", "orders.manage", "payments.record"))


class DocumentLinksView(Guarded):
    required_permission = LINK_PERMISSIONS

    @extend_schema(
        operation_id="document_links",
        tags=TAGS,
        parameters=[
            OpenApiParameter("kind", str, enum=links.K.values, required=True),
            OpenApiParameter("object_id", str, required=True),
        ],
        responses=s.DocumentLinkRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        data = s.DocumentRefSerializer(data=request.query_params)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if not _user(request).has_permission_code(links.SOURCES[v["kind"]].permission):
            raise NotFound()
        rows = links.links_for(v["kind"], v["object_id"])
        return Response(s.DocumentLinkRowSerializer(rows, many=True).data)


class DocumentLinksRevokeView(Guarded):
    required_permission = LINK_PERMISSIONS

    @extend_schema(
        operation_id="document_links_revoke",
        tags=TAGS,
        request=s.DocumentRefSerializer,
        responses=s.RevokedSerializer,
    )
    def post(self, request: Request) -> Response:
        data = s.DocumentRefSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return Response({"revoked": links.revoke(v["kind"], v["object_id"], by=_user(request))})


# --- Per shop: reminder pause, WhatsApp consent ------------------------------------------------


def _shop(request: Request, retailer_id: UUID) -> Any:
    shop = retailer_for(_user(request), retailer_id)
    if shop is None:
        raise NotFound()
    return shop


class ReminderPauseView(Guarded):
    required_permissions = {
        "GET": AnyOf(("credit.manage", "ledger.view")),
        "POST": "credit.manage",
        "DELETE": "credit.manage",
    }

    def _state(self, retailer_id: UUID) -> Response:
        pause = jobs.active_pause(retailer_id, today_ist())
        return Response(s.ReminderPauseStateSerializer({"pause": pause}).data)

    @extend_schema(
        operation_id="retailer_reminder_pause", tags=TAGS, responses=s.ReminderPauseStateSerializer
    )
    def get(self, request: Request, retailer_id: UUID) -> Response:
        return self._state(_shop(request, retailer_id).pk)

    @extend_schema(
        operation_id="retailer_reminder_pause_set",
        tags=TAGS,
        request=s.ReminderPauseInputSerializer,
        responses=s.ReminderPauseStateSerializer,
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        shop = _shop(request, retailer_id)
        data = s.ReminderPauseInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        jobs.pause_reminders(shop.pk, reason=v["reason"], until=v["until"], by=_user(request))
        return self._state(shop.pk)

    @extend_schema(
        operation_id="retailer_reminder_pause_end",
        tags=TAGS,
        responses={200: s.ReminderPauseStateSerializer},
    )
    def delete(self, request: Request, retailer_id: UUID) -> Response:
        shop = _shop(request, retailer_id)
        jobs.resume_reminders(shop.pk, by=_user(request))
        return self._state(shop.pk)


def consent_state(shop: Any) -> dict[str, Any]:
    from apps.platform.selectors import is_feature_enabled

    return {
        "opted_in": shop.whatsapp_opt_in,
        "source": shop.whatsapp_opt_in_source,
        "opted_in_at": shop.whatsapp_opt_in_at,
        "opted_out_at": shop.whatsapp_opt_out_at,
        "prompt": consent.should_prompt(shop),
        "whatsapp_available": is_feature_enabled("whatsapp", shop.tenant_id),
    }


class RetailerConsentView(Guarded):
    required_permissions = {"GET": "retailers.view", "PUT": "retailers.manage"}

    @extend_schema(
        operation_id="retailer_whatsapp_consent", tags=TAGS, responses=s.ConsentStateSerializer
    )
    def get(self, request: Request, retailer_id: UUID) -> Response:
        return Response(s.ConsentStateSerializer(consent_state(_shop(request, retailer_id))).data)

    @extend_schema(
        operation_id="retailer_whatsapp_consent_update",
        tags=TAGS,
        request=s.StaffConsentInputSerializer,
        responses=s.ConsentStateSerializer,
    )
    def put(self, request: Request, retailer_id: UUID) -> Response:
        shop = _shop(request, retailer_id)
        data = s.StaffConsentInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        updated = consent.set_whatsapp_consent(
            shop.pk,
            v["agreed"],
            source=consent.Source.STAFF,
            by=_user(request),
            confirmed=v["confirmed"],
        )
        return Response(s.ConsentStateSerializer(consent_state(updated)).data)


# --- GST rate changes (dashboard card) ---------------------------------------------------------


class UpcomingRateChangesView(Guarded):
    required_permission = "products.view"

    @extend_schema(
        operation_id="tax_upcoming_rate_changes",
        tags=TAGS,
        responses=s.RateChangeSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        changes = jobs.upcoming_rate_changes(today_ist())
        return Response(s.RateChangeSerializer(changes, many=True).data)
