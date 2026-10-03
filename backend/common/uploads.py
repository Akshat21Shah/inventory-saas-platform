"""Validating uploaded images on the server (ADR-027): type from content, size and dimensions."""

import io
from dataclasses import dataclass

from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext as _
from PIL import Image, UnidentifiedImageError

from common.errors import InvalidFields
from common.numbers import fill

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


def validate_image(
    upload: "UploadedFile[bytes]",
    field: str = "file",
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_side: int = MAX_IMAGE_SIDE,
) -> ValidImage:
    """PNG, JPEG or WebP only, judged by content (never by name). SVG is refused: it can carry
    scripts. At most ``max_bytes`` (2 MB) and ``max_side`` (4096 px) on either side."""
    data = upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise InvalidFields(
            {
                field: [
                    fill(
                        _("The image is larger than %(value)s MB."),
                        {"value": max_bytes // (1024 * 1024)},
                    )
                ]
            }
        )
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format or ""
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidFields({field: [_("Upload a PNG, JPEG or WebP image.")]}) from exc
    if fmt not in _FORMATS:
        raise InvalidFields({field: [_("Upload a PNG, JPEG or WebP image.")]})
    if width > max_side or height > max_side:
        raise InvalidFields(
            {
                field: [
                    fill(
                        _("The image must be at most %(max_side)s px wide and high."),
                        {"max_side": max_side},
                    )
                ]
            }
        )
    content_type, extension = _FORMATS[fmt]
    return ValidImage(data, content_type, extension, width, height)
