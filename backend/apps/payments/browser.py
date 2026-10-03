"""The Android app paying in the browser (ADR-061 item 9; owner, checkpoint review item 7).

UPI apps open from a browser, not from inside an app's web view, so the app opens the checkout's
payment page in a Chrome Custom Tab:

1. ``browser_link``: for the shop's own open checkout, the page's address with a one-time code
   (one minute) in its fragment, which never reaches a server's logs.
2. ``open_session``: the page trades the code for a session it keeps in the tab.
3. ``session_checkout`` and ``note_session_outcome``: all the session can do is read that one
   checkout and note what the page saw. It is never a shop session. It ends when the checkout is
   paid or expires (30 minutes at most), whichever comes first: the page reads the final status
   once, and then nothing.

Back in the app, the app asks the server for the checkout's status; it never trusts the tab.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.utils import timezone
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.accounts.retailer_login import is_active_retailer_login
from apps.payments import online
from apps.payments.models import CheckoutBrowserSession, PaymentIntent
from apps.platform.models import Tenant
from apps.platform.selectors import get_platform_setting, tenant_by_slug
from common import ratelimit
from common.error_codes import ErrorCode
from common.errors import DomainError
from common.hosts import HostContext, HostKind, web_url
from common.tenancy import tenant_transaction

LINK_SECONDS = 60


class PayPageClosed(DomainError):
    status_code = 401
    code = ErrorCode.PAY_PAGE_CLOSED
    default_message = gettext_lazy("This payment page has closed. Go back to the app to pay.")


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _open(intent: PaymentIntent, until: datetime) -> bool:
    return intent.status in PaymentIntent.ACTIVE and min(until, intent.expires_at) > timezone.now()


def browser_link(intent: PaymentIntent, user: User) -> tuple[str, datetime]:
    """The payment page's address for this checkout, opened once by a one-minute code. A new link
    ends the checkout's earlier pages, so only the latest tab can pay."""
    ratelimit.hit("browser-pay:user", str(user.pk), 20, 60)
    if not _open(intent, intent.expires_at):
        raise PayPageClosed()
    now = timezone.now()
    CheckoutBrowserSession.objects.filter(intent=intent, ended_at__isnull=True).update(
        ended_at=now, updated_at=now
    )
    raw = secrets.token_urlsafe(32)
    expires = now + timedelta(seconds=LINK_SECONDS)
    CheckoutBrowserSession.objects.create(
        intent=intent,
        user=user,
        code_hash=_hash(raw),
        code_expires_at=expires,
        expires_at=intent.expires_at,
        created_by=user,
    )
    slug = Tenant.objects.get(pk=intent.tenant_id).slug
    return f"{web_url(f'/pay/{intent.pk}', tenant_slug=slug)}#{urlencode({'code': raw})}", expires


def _host_tenant(host: HostContext) -> Tenant:
    slug = host.tenant_slug if host.kind == HostKind.TENANT else None
    tenant = tenant_by_slug(slug) if slug else None
    if tenant is None or tenant.status != Tenant.Status.ACTIVE:
        raise PayPageClosed()
    return tenant


def _still_allowed(row: CheckoutBrowserSession, tenant: Tenant) -> bool:
    user = row.user
    return user.is_active and is_active_retailer_login(user, tenant.pk)


def open_session(
    code: str, host: HostContext, ip: str | None
) -> tuple[str, CheckoutBrowserSession]:
    """Trade the link's code (once, within its minute, on its distributor's address) for the
    page's session."""
    ratelimit.hit(
        "browser-pay:ip", ip, get_platform_setting("platform.login_rate_per_ip_per_minute"), 60
    )
    tenant = _host_tenant(host)
    session = secrets.token_urlsafe(32)
    now = timezone.now()
    with tenant_transaction(tenant.pk):
        used = CheckoutBrowserSession.objects.filter(
            code_hash=_hash(code or ""),
            opened_at__isnull=True,
            ended_at__isnull=True,
            code_expires_at__gt=now,
        ).update(opened_at=now, session_hash=_hash(session), updated_at=now)
        if used != 1:
            raise PayPageClosed()
        row = CheckoutBrowserSession.objects.select_related("intent", "user").get(
            code_hash=_hash(code)
        )
        if not _still_allowed(row, tenant) or not _open(row.intent, row.expires_at):
            raise PayPageClosed()
    return session, row


def _session(raw: str, tenant: Tenant) -> CheckoutBrowserSession:
    row: CheckoutBrowserSession | None = (
        CheckoutBrowserSession.objects.select_related(
            "user", "intent__invoice", "intent__payment", "intent__retailer"
        )
        .filter(session_hash=_hash(raw), ended_at__isnull=True)
        .exclude(session_hash="")
        .first()
        if raw
        else None
    )
    if row is None or not _still_allowed(row, tenant):
        raise PayPageClosed()
    return row


def session_checkout(raw: str, host: HostContext) -> tuple[PaymentIntent, bool]:
    """The page's checkout and whether the page is still open. Once the checkout is paid or has
    expired, this answers one last time and the session ends."""
    tenant = _host_tenant(host)
    with tenant_transaction(tenant.pk):
        row = _session(raw, tenant)
        if _open(row.intent, row.expires_at):
            return row.intent, True
        now = timezone.now()
        row.ended_at = now
        row.save(update_fields=["ended_at", "updated_at"])
        return row.intent, False


def note_session_outcome(raw: str, host: HostContext, outcome: str) -> PaymentIntent:
    """What the page saw (informational, as on the web: only the gateway's word counts)."""
    tenant = _host_tenant(host)
    with tenant_transaction(tenant.pk):
        row = _session(raw, tenant)
        if not _open(row.intent, row.expires_at):
            raise PayPageClosed()
        return online.note_outcome(row.intent, outcome)
