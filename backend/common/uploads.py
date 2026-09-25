"""Validating uploaded images on the server (ADR-027): type from content, size and dimensions."""

import io
from dataclasses import dataclass

from django.core.files.uploadedfile import UploadedFile
from PIL import Image, UnidentifiedImageError

from common.errors import InvalidFields

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_SIDE = 4096
_FORMATS = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "WEBP": ("image/webp", "webp"),
}


@dataclass(frozen=True)
class ValidImage:
    data: bytes
    content_type: str
    extension: str
    width: int
    height: int


def validate_image(upload: "UploadedFile[bytes]", field: str = "file") -> ValidImage:
    """PNG, JPEG or WebP only, judged by content (never by name). SVG is refused: it can carry
    scripts. At most 2 MB and 4096 px on either side."""
    data = upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidFields({field: ["The image is larger than 2 MB."]})
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format or ""
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidFields({field: ["Upload a PNG, JPEG or WebP image."]}) from exc
    if fmt not in _FORMATS:
        raise InvalidFields({field: ["Upload a PNG, JPEG or WebP image."]})
    if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
        raise InvalidFields(
            {field: [f"The image must be at most {MAX_IMAGE_SIDE} px wide and high."]}
        )
    content_type, extension = _FORMATS[fmt]
    return ValidImage(data, content_type, extension, width, height)
