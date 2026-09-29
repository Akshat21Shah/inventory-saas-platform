"""Super admin notification APIs: the platform's default texts (incl. approved WhatsApp
templates) and failed messages across tenants (audited platform alias)."""

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit import services as audit
from apps.notifications import delivery, selectors, texts
from apps.notifications.api import serializers as s
from apps.notifications.api.views import Guarded, Newest, _uuid
from apps.notifications.models import Notification, PlatformTemplate
from apps.platform.api.views import CommitThenReadView
from common.errors import InvalidFields, NotFound
from common.platform_db import platform_db
from common.tenancy import tenant_context

TAGS = ["platform"]
SETTINGS, SUPPORT = "platform.settings.manage", "platform.tenants.manage"


class PlatformTemplateSerializer(serializers.ModelSerializer[PlatformTemplate]):
    class Meta:
        model = PlatformTemplate
        fields = [
            "id",
            "event_code",
            "audience",
            "channel",
            "locale",
            "subject",
            "body",
            "whatsapp_template_name",
            "whatsapp_language",
            "whatsapp_category",
            "variables",
            "updated_at",
        ]


class PlatformTemplatesView(Guarded, generics.ListAPIView[PlatformTemplate]):
    required_permission = SETTINGS
    serializer_class = PlatformTemplateSerializer
    pagination_class = None

    def get_queryset(self) -> QuerySet[PlatformTemplate]:
        rows = PlatformTemplate.objects.all().order_by(
            "event_code", "audience", "channel", "locale"
        )
        event = self.request.query_params.get("event")
        return rows.filter(event_code=event) if event else rows

    @extend_schema(
        operation_id="platform_notification_templates",
        tags=TAGS,
        parameters=[OpenApiParameter("event", str, required=False)],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class PlatformTemplateView(Guarded):
    required_permission = SETTINGS

    @extend_schema(
        operation_id="platform_notification_template_update",
        tags=TAGS,
        request=s.PlatformTextInputSerializer,
        responses=PlatformTemplateSerializer,
    )
    def put(self, request: Request, event: str, channel: str) -> Response:
        data = s.PlatformTextInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        row = texts.save_platform_text(
            texts.TextInput(event, channel, v["locale"], v["subject"], v["body"], v["audience"]),
            texts.WhatsAppFields(
                v["whatsapp_template_name"], v["whatsapp_language"], v["whatsapp_category"]
            ),
        )
        return Response(PlatformTemplateSerializer(row).data)


class PlatformTextPreviewView(Guarded):
    required_permission = SETTINGS

    @extend_schema(
        operation_id="platform_notification_text_preview",
        tags=TAGS,
        request=s.TextPreviewInputSerializer,
        responses=s.TextPreviewSerializer,
    )
    def post(self, request: Request) -> Response:
        data = s.TextPreviewInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        text = texts.TextInput(
            v["event"], v["channel"], v["locale"], v["subject"], v["body"], v["audience"]
        )
        return Response(s.TextPreviewSerializer(texts.preview(text, "Sharma Distributors")).data)


class PlatformFailuresView(Guarded, generics.ListAPIView[Notification]):
    required_permission = SUPPORT
    serializer_class = s.PlatformFailureSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Notification]:
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.unscoped().none()
        return selectors.failures_everywhere(
            _uuid(self.request.query_params.get("tenant"), "tenant")
        )

    @extend_schema(
        operation_id="platform_notification_failures",
        tags=TAGS,
        parameters=[OpenApiParameter("tenant", str, required=False)],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class PlatformFailureRetryView(CommitThenReadView):
    required_permission = SUPPORT

    @extend_schema(
        operation_id="platform_notification_failure_retry",
        tags=TAGS,
        request=None,
        responses=s.PlatformFailureSerializer,
    )
    def post(self, request: Request, notification_id: UUID) -> Response:
        alias = platform_db("notifications.platform_retry")
        found = Notification.objects.unscoped().using(alias).filter(pk=notification_id).first()
        if found is None:
            raise NotFound()
        with transaction.atomic(), tenant_context(found.tenant_id):  # committed before the read
            if not delivery.retry(found.pk):
                raise InvalidFields({"status": ["Only a failed message can be tried again."]})
            audit.record(
                "notifications.delivery_retried",
                target=found,
                target_repr=f"{found.event_code} {found.channel}",
                tenant_id=found.tenant_id,
            )
        row = Notification.objects.unscoped().using(alias).select_related("tenant", "retailer")
        return Response(s.PlatformFailureSerializer(row.get(pk=notification_id)).data)
