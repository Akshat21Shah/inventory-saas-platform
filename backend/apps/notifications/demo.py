"""Demo notifications for ``make seed`` (dev only): WhatsApp switched on (the mock sends nothing),
every other shop agreed to WhatsApp (as recorded by staff), and one running announcement.
Idempotent; the orders and bills the seed makes produce their own messages through the worker."""

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.notifications import announcements, consent
from apps.notifications.models import Announcement
from apps.retailers.models import Retailer


def seed_notifications(tenant: Any, owner: Any) -> int:
    """Returns the shops that agreed to WhatsApp."""
    from apps.platform.models import FeatureFlag, TenantFeature
    from apps.platform.selectors import invalidate_tenant_features

    TenantFeature.objects.get_or_create(
        flag=FeatureFlag.objects.get(code="whatsapp"), defaults={"enabled": True}
    )
    invalidate_tenant_features(tenant.pk)
    shops = list(Retailer.objects.filter(deleted_at__isnull=True).order_by("code"))
    for shop in shops[::2]:
        consent.set_whatsapp_consent(
            shop.pk, True, source=consent.Source.STAFF, by=owner, confirmed=True
        )
    if not Announcement.objects.exists():
        announcements.save(
            announcements.AnnouncementInput(
                "Diwali delivery timings",
                "Orders placed after 2 PM will be delivered the next working day.",
                timezone.now() - timedelta(hours=1),
                timezone.now() + timedelta(days=30),
            ),
            by=owner,
        )
    return len(shops[::2])
