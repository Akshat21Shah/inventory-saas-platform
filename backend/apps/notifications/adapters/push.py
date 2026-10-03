"""Push notifications to the Android shop app (ADR-061 item 7).

``mock`` in development and tests (refused elsewhere, ``notifications.E003``); ``fcm`` sends
straight through Firebase Cloud Messaging's HTTP v1 API with the platform's Firebase service
account (``FCM_SERVICE_ACCOUNT_JSON``, from the secrets manager; pre-production item 49).

TODO(verify) against Firebase's documentation before production: the OAuth 2.0 token exchange
for a service account (JWT bearer grant, scope ``firebase.messaging``), the send request
(``projects/{id}/messages:send``: ``token``, ``notification``, string-only ``data``,
``android.priority`` and ``android.notification.channel_id``), and the errors: an unknown or
expired token is reported as 404 ``UNREGISTERED`` (switched off here), 429 and 5xx are worth
retrying.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol
from uuid import uuid4

import jwt
import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from apps.notifications.adapters.base import DeliveryError, PermanentDeliveryError, SendResult

logger = logging.getLogger(__name__)

# The app creates this Android notification channel ("Messages"); the phone's settings show it.
ANDROID_CHANNEL = "messages"


@dataclass(frozen=True)
class PushMessage:
    token: str
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)  # FCM data values are strings
    urgent: bool = True


class UnregisteredDevice(PermanentDeliveryError):
    """The phone no longer has this token (app removed, data cleared): switch it off."""


class PushSender(Protocol):
    def send(self, message: PushMessage) -> SendResult: ...


class MockPushSender:
    """Records pushes in memory (tests read ``outbox``; tokens in ``unregistered`` fail like a
    removed app) and, in development, copies each to Mailpit as ``[Push mock] …``."""

    outbox: ClassVar[list[PushMessage]] = []
    unregistered: ClassVar[set[str]] = set()

    def send(self, message: PushMessage) -> SendResult:
        from common.mock_mailbox import copy_to_mailpit

        if message.token in self.unregistered:
            raise UnregisteredDevice("UNREGISTERED")
        self.outbox.append(message)
        logger.info("mock push sent", extra={"token_tail": message.token[-6:]})
        copy_to_mailpit(
            "Push",
            f"phone …{message.token[-6:]}",
            f"{message.title} — {message.body}",
            {key.title(): value for key, value in message.data.items()},
        )
        return SendResult("push-mock", f"mock-{uuid4().hex[:12]}")


class FcmPushSender:
    """Firebase Cloud Messaging HTTP v1 (see the module's TODO(verify))."""

    SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
    SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
    TIMEOUT = 10
    _TOKEN_CACHE_KEY = "fcm:access-token"  # noqa: S105 - a cache key, not a secret

    def __init__(self, service_account: dict[str, Any]) -> None:
        try:
            self.project = service_account["project_id"]
            self.client_email = service_account["client_email"]
            self.private_key = service_account["private_key"]
            self.token_uri = service_account.get("token_uri", "https://oauth2.googleapis.com/token")
        except KeyError as exc:
            raise ImproperlyConfigured(f"FCM service account without {exc}") from exc

    def _access_token(self) -> str:
        cached: str | None = cache.get(self._TOKEN_CACHE_KEY)
        if cached:
            return cached
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": self.client_email,
                "scope": self.SCOPE,
                "aud": self.token_uri,
                "iat": now,
                "exp": now + 3600,
            },
            self.private_key,
            algorithm="RS256",
        )
        try:
            response = requests.post(
                self.token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=self.TIMEOUT,
            )
        except requests.RequestException as exc:
            raise DeliveryError(f"FCM sign-in failed: {type(exc).__name__}") from exc
        if not response.ok:
            raise DeliveryError(f"FCM sign-in refused: HTTP {response.status_code}")
        body = response.json()
        token: str = body["access_token"]
        cache.set(self._TOKEN_CACHE_KEY, token, max(60, int(body.get("expires_in", 3600)) - 300))
        return token

    def send(self, message: PushMessage) -> SendResult:
        payload: dict[str, Any] = {
            "message": {
                "token": message.token,
                "notification": {"title": message.title, "body": message.body},
                "data": message.data,
                "android": {
                    "priority": "HIGH" if message.urgent else "NORMAL",
                    "notification": {"channel_id": ANDROID_CHANNEL},
                },
            }
        }
        try:
            response = requests.post(
                self.SEND_URL.format(project=self.project),
                json=payload,
                headers={"Authorization": f"Bearer {self._access_token()}"},
                timeout=self.TIMEOUT,
            )
        except requests.RequestException as exc:
            raise DeliveryError(f"FCM unreachable: {type(exc).__name__}") from exc
        if response.ok:
            return SendResult("fcm", str(response.json().get("name", ""))[:120])
        error = _fcm_error(response)
        if response.status_code == 404 or error == "UNREGISTERED":
            raise UnregisteredDevice(error or "UNREGISTERED")
        if response.status_code in (401, 403):
            cache.delete(self._TOKEN_CACHE_KEY)  # signed in again on the next try
            raise DeliveryError(f"FCM refused the sign-in: {error or response.status_code}")
        if response.status_code == 429 or response.status_code >= 500:
            raise DeliveryError(f"FCM busy: {error or response.status_code}")
        raise PermanentDeliveryError(f"FCM refused the message: {error or response.status_code}")


def _fcm_error(response: requests.Response) -> str:
    """The FCM error code (``UNREGISTERED``, ``INVALID_ARGUMENT``, …) if the body has one."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return ""
    for detail in error.get("details", []):
        if detail.get("errorCode"):
            return str(detail["errorCode"])
    return str(error.get("status", ""))


def get_push_sender() -> PushSender:
    provider = settings.PUSH_PROVIDER
    if provider == "mock":
        if not settings.ALLOW_MOCK_INTEGRATIONS:
            raise ImproperlyConfigured("Push provider 'mock' is only allowed in dev and test")
        return MockPushSender()
    if provider == "fcm":
        if not settings.FCM_SERVICE_ACCOUNT_JSON:
            raise ImproperlyConfigured("PUSH_PROVIDER 'fcm' needs FCM_SERVICE_ACCOUNT_JSON")
        return FcmPushSender(json.loads(settings.FCM_SERVICE_ACCOUNT_JSON))
    raise ImproperlyConfigured(f"Unknown push provider {provider!r}")
