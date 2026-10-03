"""The translation sheet, review progress and 'Suggest a better word' (ADR-060 items 11, 14)."""

from typing import Any

from rest_framework import serializers

from apps.platform.models import TextSuggestion


class SuggestionCreateSerializer(serializers.Serializer[Any]):
    language = serializers.CharField(max_length=5)
    screen = serializers.CharField(max_length=300, help_text="The page's address.")
    current_text = serializers.CharField(max_length=500, required=False, allow_blank=True)
    suggestion = serializers.CharField(max_length=500)


class SuggestionCreatedSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()


class SuggestionSerializer(serializers.ModelSerializer[TextSuggestion]):
    tenant_name = serializers.SerializerMethodField()
    sent_by = serializers.SerializerMethodField()
    resolved_by = serializers.SerializerMethodField()

    class Meta:
        model = TextSuggestion
        fields = [
            "id",
            "language",
            "screen",
            "current_text",
            "suggestion",
            "status",
            "tenant_name",
            "sent_by",
            "created_at",
            "resolved_by",
            "resolved_at",
        ]

    def get_tenant_name(self, obj: TextSuggestion) -> str:
        return obj.tenant.name if obj.tenant else ""

    def get_sent_by(self, obj: TextSuggestion) -> str:
        user = obj.user
        return (user.full_name or user.email or user.phone or "") if user else ""

    def get_resolved_by(self, obj: TextSuggestion) -> str:
        return obj.resolved_by.full_name if obj.resolved_by else ""


class SuggestionFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(
        choices=TextSuggestion.Status.choices, required=False, allow_blank=True
    )
    language = serializers.CharField(max_length=5, required=False, allow_blank=True)


class SuggestionUpdateSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=TextSuggestion.Status.choices)


class TextProgressSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()
    native = serializers.CharField()
    enabled = serializers.BooleanField(help_text="On for everyone (platform.languages_enabled).")
    total = serializers.IntegerField(help_text="Texts in the app.")
    translated = serializers.IntegerField()
    reviewed = serializers.IntegerField(help_text="Reviewed by a native speaker.")
    new_suggestions = serializers.IntegerField()
