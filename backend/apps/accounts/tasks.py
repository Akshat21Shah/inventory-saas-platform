"""Celery tasks for accounts: outbound email (retried with backoff) and housekeeping."""

import logging

from celery import shared_task
from django.core.mail import send_mail

from apps.accounts.models import User

logger = logging.getLogger(__name__)


@shared_task(
    name="accounts.send_account_locked_email",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=1800,
    retry_jitter=True,
    max_retries=8,
)
def send_account_locked_email(user_id: str) -> None:
    """Tell the account owner that sign-in was paused after repeated failures (ADR-030).

    Phase 6 moves wording to the notification templates (and adds Hindi / Marathi).
    """
    user = User.objects.filter(pk=user_id).first()
    if user is None or not user.email or user.locked_until is None:
        return
    send_mail(
        subject="Sign-in to your account was paused",
        message=(
            f"Hello {user.full_name or ''},\n\n"
            "We paused sign-in to your account for a few minutes because the password was "
            "entered incorrectly several times.\n\n"
            "If this was you, wait a few minutes and try again, or reset your password.\n"
            "If it wasn't you, reset your password now: someone may be trying to get in.\n"
        ),
        from_email=None,
        recipient_list=[user.email],
    )


@shared_task(name="accounts.purge_expired_login_records")
def purge_expired_login_records() -> int:
    from apps.accounts.services import purge_expired_login_records as purge

    return purge()


@shared_task(
    name="accounts.send_password_reset_email",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=1800,
    retry_jitter=True,
    max_retries=8,
)
def send_password_reset_email(user_id: str) -> None:
    """The link is made when the email is sent; it stops working once the password changes."""
    from apps.accounts.services import password_reset_link

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or not user.email:
        return
    send_mail(
        subject="Reset your password",
        message=(
            f"Hello {user.full_name or ''},\n\n"
            "Someone asked to reset the password for your account. To choose a new password, "
            "open this link:\n\n"
            f"{password_reset_link(user)}\n\n"
            "The link works once. If you didn't ask for this, you can ignore this email.\n"
        ),
        from_email=None,
        recipient_list=[user.email],
    )
