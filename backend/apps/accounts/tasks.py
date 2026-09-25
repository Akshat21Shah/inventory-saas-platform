"""Celery tasks for accounts: outbound email (retried with backoff) and housekeeping."""

import logging
from uuid import UUID

from celery import shared_task
from django.core.mail import send_mail
from django.db import transaction

from apps.accounts.models import Invitation, User
from common.hosts import web_url
from common.task_base import TenantTask
from common.tenancy import tenant_context

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


@shared_task(
    name="accounts.send_login_otp_sms",
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_backoff_max=60,
    max_retries=3,
)
def send_login_otp_sms(phone: str, code: str, sender_name: str) -> None:
    """Short retries only: a code is useless after a few minutes (OTP_TTL_SECONDS)."""
    from apps.accounts.adapters.sms import get_sms_sender

    get_sms_sender().send_otp(phone, code, sender_name=sender_name)


@shared_task(
    name="accounts.send_invitation_email",
    base=TenantTask,
    atomic=False,  # no DB transaction held while talking to the mail server
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=1800,
    retry_jitter=True,
    max_retries=8,
)
def send_invitation_email(*, invitation_id: str, raw_token: str, tenant_id: str) -> None:
    from apps.platform.models import Tenant

    with transaction.atomic(), tenant_context(UUID(tenant_id)):
        invitation = (
            Invitation.objects.select_related("role", "invited_by", "tenant")
            .filter(pk=invitation_id, status=Invitation.Status.PENDING)
            .first()
        )
        if invitation is None:
            return
        tenant: Tenant = invitation.tenant
        inviter = invitation.invited_by.full_name if invitation.invited_by else ""
        role_name, email = invitation.role.name, invitation.email
    link = web_url(f"/invite/{raw_token}", tenant_slug=tenant.slug)
    who = f"{inviter} has" if inviter else "You have been"
    send_mail(
        subject=f"You're invited to join {tenant.name}",
        message=(
            f"Hello,\n\n{who} invited you to join {tenant.name} as {role_name}.\n\n"
            f"To accept, open this link:\n\n{link}\n\n"
            "The link works for 7 days. If you weren't expecting this, you can ignore it.\n"
        ),
        from_email=None,
        recipient_list=[email],
    )
