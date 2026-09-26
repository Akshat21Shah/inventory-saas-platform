"""Product image processing (ADR-034): originals stay private; resized WebP variants go to the
public, unlisted bucket under an unguessable, content-versioned prefix with immutable caching."""

import hashlib
import io
import secrets
from typing import Any
from uuid import UUID

from PIL import Image, ImageOps

from common.storage import IMMUTABLE, get_storage

PRODUCT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
PRODUCT_IMAGE_MAX_SIDE = 8192  # phone cameras (up to 48 MP) are fine; bombs are refused by Pillow
SIZES = {"thumb": 160, "medium": 640, "large": 1280}  # longest side, never upscaled
WEBP_QUALITY = 80


def original_key(tenant_id: UUID, product_id: UUID, image_id: UUID, extension: str) -> str:
    return f"tenants/{tenant_id}/products/{product_id}/originals/{image_id}.{extension}"


def variant_prefix(tenant_id: UUID, product_id: UUID, original: bytes) -> str:
    """A random token (so URLs can't be guessed) plus the content hash (so a changed image always
    gets a new URL)."""
    token = secrets.token_urlsafe(16)
    digest = hashlib.sha256(original).hexdigest()[:16]
    return f"tenants/{tenant_id}/products/{product_id}/{token}-{digest}"


def render_variants(original: bytes) -> dict[str, tuple[bytes, int, int]]:
    """``{size: (webp bytes, width, height)}``. EXIF orientation is applied, metadata dropped."""
    out: dict[str, tuple[bytes, int, int]] = {}
    with Image.open(io.BytesIO(original)) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        for name, side in SIZES.items():
            copy = image.copy()
            copy.thumbnail((side, side), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            copy.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=4)
            out[name] = (buffer.getvalue(), copy.width, copy.height)
    return out


def store_variants(prefix: str, variants: dict[str, tuple[bytes, int, int]]) -> dict[str, Any]:
    storage = get_storage()
    stored: dict[str, Any] = {}
    for name, (data, width, height) in variants.items():
        key = f"{prefix}/{name}.webp"
        storage.put_public(key, data, "image/webp", IMMUTABLE)
        stored[name] = {"key": key, "width": width, "height": height}
    return stored


def variant_urls(variants: dict[str, Any]) -> dict[str, str]:
    storage = get_storage()
    return {name: storage.public_url(v["key"]) for name, v in variants.items() if v.get("key")}
