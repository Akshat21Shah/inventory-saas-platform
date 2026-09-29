"""Email adapter.

- ``django`` (dev and test): Django's email backend, which is Mailpit in dev (nothing leaves the
  machine) and the in-memory outbox in tests.
- ``ses``: Amazon SES (API v2) with boto3.
  TODO(verify): the sending identity (the platform domain with DKIM/SPF), the account leaving the
  SES sandbox, the configuration set and bounce/complaint handling must be checked against the
  official SES documentation before production (PROGRESS pre-production item 9).
"""

from dataclasses import dataclass
from email.utils import formataddr, make_msgid, parseaddr
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage as DjangoEmail

from apps.notifications.adapters.base import DeliveryError, PermanentDeliveryError, SendResult


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str
    from_name: str  # the distributor: "Sharma Distributors <no-reply@platform>"
    reply_to: str = ""  # the distributor's own address


def sender_address(from_name: str) -> str:
    _, address = parseaddr(settings.DEFAULT_FROM_EMAIL)
    return formataddr((from_name, address)) if from_name else settings.DEFAULT_FROM_EMAIL


class EmailSender(Protocol):
    name: str

    def send(self, email: Email) -> SendResult: ...


class DjangoEmailSender:
    name = "django"

    def send(self, email: Email) -> SendResult:
        message_id = make_msgid(domain="notifications.local")
        message = DjangoEmail(
            subject=email.subject,
            body=email.body,
            from_email=sender_address(email.from_name),
            to=[email.to],
            reply_to=[email.reply_to] if email.reply_to else None,
            headers={"Message-ID": message_id},
        )
        try:
            message.send(fail_silently=False)
        except OSError as exc:  # SMTP down: try again later
            raise DeliveryError(str(exc)) from exc
        return SendResult(self.name, message_id)


class SesEmailSender:
    """TODO(verify): request and response shapes against the SES v2 SendEmail API reference."""

    name = "ses"

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client("sesv2", region_name=settings.SES_REGION)

    def send(self, email: Email) -> SendResult:
        from botocore.exceptions import BotoCoreError, ClientError

        request = {
            "FromEmailAddress": sender_address(email.from_name),
            "Destination": {"ToAddresses": [email.to]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": email.subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": email.body, "Charset": "UTF-8"}},
                }
            },
        }
        if email.reply_to:
            request["ReplyToAddresses"] = [email.reply_to]
        if settings.SES_CONFIGURATION_SET:
            request["ConfigurationSetName"] = settings.SES_CONFIGURATION_SET
        try:
            response = self.client.send_email(**request)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            # TODO(verify): which SES error codes are permanent.
            if code in ("MessageRejected", "BadRequestException", "NotFoundException"):
                raise PermanentDeliveryError(code) from exc
            raise DeliveryError(code or str(exc)) from exc
        except BotoCoreError as exc:
            raise DeliveryError(str(exc)) from exc
        return SendResult(self.name, str(response.get("MessageId", "")))


def get_email_sender() -> EmailSender:
    provider: str = settings.EMAIL_PROVIDER
    if provider == "django":
        return DjangoEmailSender()
    if provider == "ses":
        return SesEmailSender()
    raise ImproperlyConfigured(f"Unknown EMAIL_PROVIDER {provider!r}")
