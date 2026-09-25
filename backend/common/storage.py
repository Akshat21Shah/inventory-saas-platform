"""Object storage adapter (ADR-027). All file access goes through ``get_storage()``.

- ``s3``: AWS S3 in production, SeaweedFS in dev and CI (ADR-024), via boto3. Two clients: one talks
  to the internal endpoint, the other only signs download URLs for the endpoint browsers can reach.
- ``memory``: an in-process store for tests.
Keys are tenant-prefixed (``tenants/<tenant_id>/...``); the bucket stays private.
"""

from functools import lru_cache
from typing import Any, ClassVar, Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def presigned_get(self, key: str, expires_in: int = 300) -> str: ...


class InMemoryStorage:
    objects: ClassVar[dict[str, tuple[bytes, str]]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> bytes:
        return self.objects[key][0]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def presigned_get(self, key: str, expires_in: int = 300) -> str:
        return f"https://storage.test/{key}?expires_in={expires_in}"


class S3Storage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        common: dict[str, Any] = {
            "aws_access_key_id": settings.S3_ACCESS_KEY or None,
            "aws_secret_access_key": settings.S3_SECRET_KEY or None,
            "region_name": settings.S3_REGION,
            "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        }
        self.bucket: str = settings.S3_BUCKET
        self.client = boto3.client("s3", endpoint_url=settings.S3_ENDPOINT_URL or None, **common)
        public = settings.S3_PUBLIC_ENDPOINT_URL or settings.S3_ENDPOINT_URL or None
        self.signer = boto3.client("s3", endpoint_url=public, **common)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        body: bytes = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return body

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def presigned_get(self, key: str, expires_in: int = 300) -> str:
        url: str = self.signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in
        )
        return url


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    backend = settings.STORAGE_BACKEND
    if backend == "s3":
        return S3Storage()
    if backend == "memory":
        return InMemoryStorage()
    raise ImproperlyConfigured(f"Unknown STORAGE_BACKEND {backend!r}")
