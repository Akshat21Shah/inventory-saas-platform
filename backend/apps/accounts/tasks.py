"""Celery tasks for accounts: outbound email (retried with backoff) and housekeeping."""

import logging
from uuid import UUID

from celery import shared_task
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import Invitation, User
from common.hosts import web_url
from common.languages import speaking
from common.task_base import TenantTask
from common.tenancy import tenant_context

logger = logging.getLogger(__name__)


def send_mail(
    *, subject: str, message: str, recipient_list: list[str], from_name: str = ""
) -> None:
    """Always-sent account emails (outside the notification rules, ADR-048 item 15) through the
    same email adapter: Mailpit in dev, in-memory in tests, SES in production."""
    from apps.notifications.adapters.email import Email, get_email_sender

    sender = get_email_sender()
    for address in recipient_list:
        sender.send(Email(address, subject, message, from_name))


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

    In the person's language (ADR-060).
    """
    user = User.objects.filter(pk=user_id).first()
    if user is None or not user.email or user.locked_until is None:
        return
    with speaking(user, user.tenant_id):
        send_mail(
            subject=_("Sign-in to your account was paused"),
            message=_(
                "Hello %(name)s,\n\n"
                "We paused sign-in to your account for a few minutes because the password was "
                "entered incorrectly several times.\n\n"
                "If this was you, wait a few minutes and try again, or reset your password.\n"
                "If it wasn't you, reset your password now: someone may be trying to get in.\n"
            )
            % {"name": user.full_name or ""},
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
    with speaking(user, user.tenant_id):
        send_mail(
            subject=_("Reset your password"),
            message=_(
                "Hello %(name)s,\n\n"
                "Someone asked to reset the password for your account. To choose a new "
                "password, open this link:\n\n"
                "%(link)s\n\n"
                "The link works once. If you didn't ask for this, you can ignore this email.\n"
            )
            % {"name": user.full_name or "", "link": password_reset_link(user)},
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
        by = invitation.invited_by
    link = web_url(f"/invite/{raw_token}", tenant_slug=tenant.slug)
    # The new person has no language yet: the inviter's (ADR-060).
    with speaking(by, tenant.pk):
        values = {"inviter": inviter, "business": tenant.name, "role": role_name}
        invited = (
            _("%(inviter)s has invited you to join %(business)s as %(role)s.") % values
            if inviter
            else _("You have been invited to join %(business)s as %(role)s.") % values
        )
        send_mail(
            subject=_("You're invited to join %(business)s") % values,
            message=_(
                "Hello,\n\n%(invited)s\n\n"
                "To accept, open this link:\n\n%(link)s\n\n"
                "The link works for 7 days. If you weren't expecting this, you can ignore it.\n"
            )
            % {"invited": invited, "link": link},
            recipient_list=[email],
            from_name=tenant.name,
        )


@shared_task(name="accounts.expire_impersonation_sessions")
def expire_impersonation_sessions() -> int:
    from apps.accounts.impersonation import expire_sessions

    return expire_sessions()
