from typing import Any

from rest_framework import serializers

from apps.dataio.models import ImportJob


class ImportJobSerializer(serializers.ModelSerializer[ImportJob]):
    created_by = serializers.CharField(source="created_by.full_name", default="", read_only=True)

    class Meta:
        model = ImportJob
        fields = (
            "id",
            "kind",
            "mode",
            "status",
            "file_name",
            "problem",
            "counts",
            "notes",
            "errors",
            "changes",
            "created_by",
            "created_at",
            "validated_at",
            "committed_at",
        )
        read_only_fields = fields


class ImportJobListSerializer(serializers.ModelSerializer[ImportJob]):
    created_by = serializers.CharField(source="created_by.full_name", default="", read_only=True)

    class Meta:
        model = ImportJob
        fields = (
            "id",
            "kind",
            "mode",
            "status",
            "file_name",
            "counts",
            "created_by",
            "created_at",
            "committed_at",
        )
        read_only_fields = fields


class ImportUploadSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=ImportJob.Kind.choices)
    # No default: the distributor chooses for every import (ADR-035).
    mode = serializers.ChoiceField(
        choices=ImportJob.Mode.choices,
        error_messages={"required": "Choose “Add new only” or “Add new and update existing”."},
    )
    file = serializers.FileField(
        error_messages={"empty": "The file is empty.", "required": "Choose a file to upload."}
    )


class ExportParamsSerializer(serializers.Serializer[Any]):
    # Not "format": DRF reserves ?format= for choosing a response renderer.
    file_type = serializers.ChoiceField(choices=["xlsx", "csv"], default="xlsx")
