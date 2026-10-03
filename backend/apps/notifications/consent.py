"""WhatsApp consent (ADR-048 item 5). A shop gets WhatsApp messages only after it agreed:
in the app (the one-time prompt after sign-in, or the switch in its settings), through staff who
tick "the shop agreed" when adding or editing it, or an import column. Opting out is always
possible and stops WhatsApp at once, also for messages already waiting. Every change is audited
with its source."""

from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.notifications.models import Channel, Notification
from apps.retailers.models import Retailer
from common.errors import InvalidFields, NotFound

Source = Retailer.WhatsAppOptInSource


def set_whatsapp_consent(
    retailer_id: UUID,
    agreed: bool,
    *,
    source: str,
    by: User | None,
    confirmed: bool = False,
) -> Retailer:
    """Record the shop's choice. Staff opting a shop in must confirm the shop agreed."""
    if source not in Source.values:
        raise InvalidFields({"source": [_("Unknown source.")]})
    if agreed and source == Source.STAFF and not confirmed:
        raise InvalidFields(
            {"whatsapp_consent_confirmed": [_("Confirm the shop agreed to WhatsApp messages.")]}
        )
    shop: Retailer | None = (
        Retailer.objects.select_for_update().filter(pk=retailer_id, deleted_at__isnull=True).first()
    )
    if shop is None:
        raise NotFound()
    if shop.whatsapp_opt_in == agreed:
        return shop  # nothing changes (an import saying "yes" again, a double tap)
    now = timezone.now()
    shop.whatsapp_opt_in = agreed
    if agreed:
        shop.whatsapp_opt_in_at, shop.whatsapp_opt_in_source = now, source
    else:
        shop.whatsapp_opt_out_at = now
    shop.save(
        update_fields=[
            "whatsapp_opt_in",
            "whatsapp_opt_in_at",
            "whatsapp_opt_in_source",
            "whatsapp_opt_out_at",
            "updated_at",
        ]
    )
    if not agreed:  # stop what is still waiting (quiet hours, retries)
        Notification.objects.filter(
            retailer=shop,
            channel=Channel.WHATSAPP,
            address=shop.mobile,
            status=Notification.Status.PENDING,
        ).update(
            status=Notification.Status.SKIPPED,
            skip_reason=Notification.SkipReason.NO_WHATSAPP_OPT_IN,
            updated_at=now,
        )
    audit.record(
        "retailers.whatsapp_opted_in" if agreed else "retailers.whatsapp_opted_out",
        target=shop,
        target_repr=shop.shop_name,
        metadata={"source": source, "by_shop": source == Source.SHOP_APP},
    )
    return shop


def mark_prompted(retailer_id: UUID) -> None:
    """The one-time question after sign-in was shown (asked once, whatever the answer)."""
    Retailer.objects.filter(pk=retailer_id, whatsapp_prompted_at__isnull=True).update(
        whatsapp_prompted_at=timezone.now()
    )


def should_prompt(shop: Retailer) -> bool:
    return not shop.whatsapp_opt_in and shop.whatsapp_prompted_at is None


def opted_in_count() -> dict[str, int]:
    """For the rules screen: how many of the tenant's shops agreed."""
    shops = Retailer.objects.filter(deleted_at__isnull=True)
    return {"opted_in": shops.filter(whatsapp_opt_in=True).count(), "shops": shops.count()}
