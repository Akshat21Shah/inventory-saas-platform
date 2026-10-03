"""Daily notification jobs, per tenant (the tenant is set; each run is idempotent per day because
its notification ids are derived from the tenant, the subject and the date).

- Payment reminders (ADR-048 item 10): one message per shop listing what it has to pay, on the
  days of ⚙ ``notifications.payment_reminder_days`` counted from its oldest bill's due date
  (a minus number is days before it), then every ⚙ ``notifications.payment_reminder_repeat_days``.
  Compulsory for the shop; staff with ``credit.manage`` can pause them per shop.
- Handover reminders (item 11): collections still with a salesman after ⚙
  ``notifications.handover_reminder_days`` days, one digest per salesman.
- GST rate changes (item 12): products whose rate changes in 7 days.
- The daily summary (ADR-056): once the distributor's summary time has passed, one message per
  person the rules name, with only what their permissions show; checked every 15 minutes, sent
  once a day."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from django.db.models import Count, Min, Q, Sum
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.templatetags.documents import day, rate, rupees
from apps.notifications import consumer, delivery
from apps.notifications.context import EventContext, current_tenant, distributor_name, listing
from apps.notifications.models import ReminderPause
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from common.errors import InvalidFields, NotFound
from common.numbers import fill, grouped

NAMESPACE = UUID("5d6f1f4e-0c1b-4c5e-9a57-2f4b8e9d6a10")
RATE_CHANGE_NOTICE_DAYS = 7
ZERO = Decimal("0")


def job_event_id(*parts: object) -> UUID:
    """The same id for the same job, subject and day: a second run creates nothing."""
    return uuid5(NAMESPACE, ":".join(str(p) for p in parts))


def notify(event_id: UUID, ctx: EventContext) -> int:
    tenant = current_tenant()
    ctx.values.setdefault("distributor", distributor_name(tenant))
    created = consumer.fan_out(event_id, ctx, tenant)
    delivery.after_fan_out(event_id)
    return created


# --- Payment reminders --------------------------------------------------------------------------


def parse_days(text: str) -> list[int]:
    return sorted({int(part) for part in text.split(",") if part.strip()})


def reminder_due(days_since_due: int, days: list[int], repeat: int) -> bool:
    """Today is a reminder day for a bill ``days_since_due`` past its due date (negative:
    before it)."""
    if not days:
        return False
    if days_since_due in days:
        return True
    last = days[-1]
    return repeat > 0 and days_since_due > last and (days_since_due - last) % repeat == 0


def active_pause(retailer_id: UUID, today: date) -> ReminderPause | None:
    return (
        ReminderPause.objects.filter(retailer_id=retailer_id, ended_at__isnull=True)
        .filter(Q(until__isnull=True) | Q(until__gte=today))
        .first()
    )


def in_english(make: Callable[[], EventContext]) -> EventContext:
    """A scheduled message's context, made in English and remade in each recipient's language
    when sent (ADR-060)."""
    with translation.override("en"):
        ctx = make()
    ctx.rebuild = make
    return ctx


def payment_reminders(today: date) -> int:
    """Remind each shop due a reminder today. Returns the shops reminded (paused ones count:
    their rows are kept as "Not sent: paused")."""
    from apps.ledger.selectors import open_dues

    days = parse_days(str(get_setting("notifications.payment_reminder_days")))
    repeat = int(get_setting("notifications.payment_reminder_repeat_days"))
    if not days:
        return 0
    window = today + timedelta(days=max(0, -days[0]))  # bills due within the "before" days
    per_shop = defaultdict(list)
    for due in open_dues():
        if due.due_date <= window:
            per_shop[due.retailer_id].append(due)
    shops = Retailer.objects.filter(pk__in=list(per_shop), deleted_at__isnull=True)
    reminded = 0
    for shop in shops:
        dues = per_shop[shop.pk]
        oldest = min(d.due_date for d in dues)
        if not reminder_due((today - oldest).days, days, repeat):
            continue
        late = [d for d in dues if d.due_date < today]
        total = sum((d.balance_due for d in dues), ZERO)
        overdue = sum((d.balance_due for d in late), ZERO)
        paused = active_pause(shop.pk, today) is not None

        def make(shop: Retailer = shop, dues: list[Any] = dues, late: list[Any] = late,
                 total: Decimal = total, overdue: Decimal = overdue, oldest: date = oldest,
                 paused: bool = paused) -> EventContext:  # fmt: skip
            if late:
                note = fill(
                    _("%(amount)s overdue since %(date)s"),
                    {
                        "amount": rupees(overdue),
                        "date": day(min(d.due_date for d in late)),
                    },
                )
            else:
                note = fill(_("due on %(date)s"), {"date": day(oldest)})
            return EventContext(
                "payment.reminder",
                {
                    "shop": shop.shop_name,
                    "bills": fill(
                        ngettext("%(count)s bill", "%(count)s bills", len(dues)),
                        {"count": len(dues)},
                    ),
                    "amount": rupees(total),
                    "overdue": rupees(overdue),
                    "due_note": note,
                },
                retailer=shop,
                salesperson_id=shop.salesperson_id,
                shop_path="/shop/invoices",
                staff_path=f"/manage/retailers/{shop.pk}/ledger",
                extra={"paused": paused},
            )

        notify(job_event_id(shop.tenant_id, "payment.reminder", shop.pk, today), in_english(make))
        reminded += 1
    return reminded


def pause_reminders(
    retailer_id: UUID, *, reason: str, until: date | None, by: User
) -> ReminderPause:
    """Stop payment reminders for one shop (``credit.manage``), until a date or until resumed."""
    from common.dates import today_ist

    if not reason.strip():
        raise InvalidFields({"reason": [_("Say why reminders are paused.")]})
    if until is not None and until < today_ist():
        raise InvalidFields({"until": [_("Choose today or a later date.")]})
    shop = Retailer.objects.filter(pk=retailer_id, deleted_at__isnull=True).first()
    if shop is None:
        raise NotFound()
    ReminderPause.objects.filter(retailer=shop, ended_at__isnull=True).update(
        ended_at=timezone.now()
    )  # replaced by the new one
    pause: ReminderPause = ReminderPause.objects.create(
        retailer=shop, reason=reason.strip()[:300], until=until, created_by=by
    )
    audit.record(
        "notifications.reminders_paused",
        target=shop,
        target_repr=shop.shop_name,
        metadata={"reason": pause.reason, "until": until.isoformat() if until else None},
    )
    return pause


def resume_reminders(retailer_id: UUID, *, by: User) -> bool:
    shop = Retailer.objects.filter(pk=retailer_id, deleted_at__isnull=True).first()
    if shop is None:
        raise NotFound()
    ended = ReminderPause.objects.filter(retailer=shop, ended_at__isnull=True).update(
        ended_at=timezone.now()
    )
    if ended:
        audit.record("notifications.reminders_resumed", target=shop, target_repr=shop.shop_name)
    return bool(ended)


# --- Handover reminders -------------------------------------------------------------------------


def handover_reminders(today: date) -> int:
    """One digest per salesman holding collections longer than the setting allows."""
    from apps.payments.models import Payment

    days = int(get_setting("notifications.handover_reminder_days"))
    held = (
        Payment.objects.filter(
            handover_status=Payment.Handover.WITH_SALESMAN,
            payment_date__lte=today - timedelta(days=days),
            collected_by__isnull=False,
        )
        .values("collected_by")
        .annotate(count=Count("id"), amount=Sum("amount"), oldest=Min("payment_date"))
    )
    names = dict(
        User.objects.filter(pk__in=[row["collected_by"] for row in held]).values_list(
            "pk", "full_name"
        )
    )
    tenant_id = current_tenant().pk
    for row in held:
        salesman = row["collected_by"]

        def make(salesman: UUID = salesman, row: dict[str, Any] = row) -> EventContext:
            return EventContext(
                "handover.reminder",
                {
                    "salesman": names.get(salesman) or _("A salesman"),
                    "count": grouped(row["count"]),
                    "amount": rupees(row["amount"]),
                    "oldest": day(row["oldest"]),
                },
                collector_id=salesman,
                staff_path="/manage/payments/handover",
            )

        notify(job_event_id(tenant_id, "handover.reminder", salesman, today), in_english(make))
    return len(held)


# --- GST rate changes ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateChange:
    product_id: UUID
    product: str
    code: str
    effective_from: date
    old_rate: Decimal
    new_rate: Decimal


def upcoming_rate_changes(today: date, *, within_days: int = 30) -> list[RateChange]:
    """Future GST changes of products that already have a rate (the dashboard card, and the
    warning 7 days before)."""
    from apps.catalog.models import ProductTaxRate

    live = ProductTaxRate.objects.filter(cancelled_at__isnull=True)
    upcoming = live.filter(
        effective_from__gt=today, effective_from__lte=today + timedelta(days=within_days)
    ).select_related("product")
    changes = []
    for row in upcoming.order_by("effective_from", "product__name"):
        before = (
            live.filter(product_id=row.product_id, effective_from__lt=row.effective_from)
            .order_by("-effective_from")
            .first()
        )
        if before is None or before.gst_rate == row.gst_rate:
            continue
        changes.append(
            RateChange(
                row.product_id,
                row.product.name,
                row.product.code,
                row.effective_from,
                before.gst_rate,
                row.gst_rate,
            )
        )
    return changes


def rate_change_warnings(today: date) -> int:
    """Staff with ``products.manage`` hear 7 days ahead which products' GST rate changes."""
    target = today + timedelta(days=RATE_CHANGE_NOTICE_DAYS)
    changes = [
        c
        for c in upcoming_rate_changes(today, within_days=RATE_CHANGE_NOTICE_DAYS)
        if c.effective_from == target
    ]
    if not changes:
        return 0
    ctx = EventContext(
        "tax.rate_change_upcoming",
        {
            "count": grouped(len(changes)),
            "change_date": day(target),
            "products": listing(
                [f"{c.product} ({rate(c.old_rate)} → {rate(c.new_rate)})" for c in changes]
            ),
        },
        staff_path="/manage/products",
    )
    notify(job_event_id(current_tenant().pk, "tax.rate_change_upcoming", target), ctx)
    return len(changes)


# --- The daily summary (ADR-056) ----------------------------------------------------------------


def summary_due(now: datetime) -> date | None:
    """Today (Indian date) when the summary should go out now, or None: switched off, a skipped
    Sunday, or before the distributor's time."""
    from common.dates import to_ist

    if not get_setting("notifications.daily_summary_enabled"):
        return None
    local = to_ist(now)
    if get_setting("notifications.daily_summary_skip_sunday") and local.weekday() == 6:
        return None
    hour, minute = (
        int(part) for part in str(get_setting("notifications.daily_summary_time")).split(":")
    )
    if local.time() < time(hour, minute):
        return None
    return local.date()


def daily_summaries(now: datetime) -> int:
    """Each person's summary of yesterday and of what needs action; returns how many people."""
    from apps.notifications.models import Notification
    from apps.notifications.summary import summary_for

    today = summary_due(now)
    if today is None:
        return 0
    tenant_id = current_tenant().pk
    yesterday = today - timedelta(days=1)
    people = {
        t.user.pk: t.user
        for t in consumer.targets("summary.daily", EventContext("summary.daily", {}))
        if t.user is not None
    }
    sent = 0
    for user in people.values():
        event_id = job_event_id(tenant_id, "summary.daily", user.pk, today)
        if Notification.objects.filter(event_id=event_id).exists():
            continue  # already sent today

        def make(user: User = user) -> EventContext:
            found = summary_for(user, yesterday)
            done = found.yesterday or [_("nothing to show")]
            waiting = found.attention or [_("nothing waiting")]
            return EventContext(
                "summary.daily",
                {
                    "date": day(yesterday),
                    "yesterday": " · ".join(done),
                    "attention": " · ".join(waiting),
                    "yesterday_lines": "\n".join(f"- {line}" for line in done),
                    "attention_lines": "\n".join(f"- {line}" for line in waiting),
                },
                staff_path="/manage",
                extra={"only_user": user.pk},
            )

        notify(event_id, in_english(make))
        sent += 1
    return sent
