from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.ai.assistant.service import MAX_QUESTION, shown_status
from apps.ai.models import AssistantQuestion
from apps.reports.registry import Kind


class AskSerializer(serializers.Serializer[Any]):
    question = serializers.CharField(min_length=3, max_length=MAX_QUESTION, trim_whitespace=True)


class FigureColumnSerializer(serializers.Serializer[Any]):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    kind = serializers.ChoiceField(choices=[k.value for k in Kind])


class FiguresSerializer(serializers.Serializer[Any]):
    tool = serializers.CharField()
    report = serializers.CharField(help_text="The report the figures come from (its code).")
    title = serializers.CharField()
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)
    columns = FigureColumnSerializer(many=True)
    rows = serializers.ListField(child=serializers.DictField())
    totals = serializers.DictField(allow_null=True)
    count = serializers.IntegerField(help_text="Rows found; at most 20 are shown.")
    own_shops = serializers.BooleanField(help_text="Only the asker's own shops.")
    notes = serializers.ListField(child=serializers.CharField())


class ToolCallSerializer(serializers.Serializer[Any]):
    name = serializers.CharField()
    args = serializers.DictField()
    ok = serializers.BooleanField()
    error = serializers.CharField(required=False)
    figures = FiguresSerializer(required=False)


class AssistantQuestionSerializer(serializers.ModelSerializer[AssistantQuestion]):
    status = serializers.SerializerMethodField()
    tools = ToolCallSerializer(many=True, read_only=True)

    class Meta:
        model = AssistantQuestion
        fields = ["id", "question", "status", "answer", "tools", "created_at", "answered_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=AssistantQuestion.Status.choices))
    def get_status(self, obj: AssistantQuestion) -> str:
        return shown_status(obj)


class AssistantToolSerializer(serializers.Serializer[Any]):
    name = serializers.CharField()
    report = serializers.CharField()


class AssistantToolsSerializer(serializers.Serializer[Any]):
    tools = AssistantToolSerializer(many=True)
