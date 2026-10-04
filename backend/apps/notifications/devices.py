"""Phones that get the shop's app notifications (ADR-061 item 7)."""

from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import DeviceToken


def register_device(user: User, token: str, platform: str, app_version: str) -> DeviceToken:
    """The app's push token for this person, in the active tenant. A token is unique per tenant:
    the same phone signing in as another of the shop's logins moves it."""
    device: DeviceToken
    device, _ = DeviceToken.objects.update_or_create(
        token=token,
        defaults={
            "user": user,
            "platform": platform,
            "app_version": app_version,
            "last_seen_at": timezone.now(),
            "is_active": True,
        },
    )
    return device


def remove_device(user: User, token: str) -> int:
    """Signing out or switching distributor: this phone stops getting this person's pushes."""
    removed, _ = DeviceToken.objects.filter(user=user, token=token).delete()
    return removed
