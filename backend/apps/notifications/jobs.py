"""Daily notification jobs, per tenant (the tenant is set; each run is idempotent per day because
its notification ids are derived from the tenant, the subject and the date).

- Payment reminders (ADR-048 item 10): one message per shop listing what it has to pay, on the
  days of ⚙ ``notifications.payment_reminder_days`` counted from its oldest bill's due date
  (a minus number is days before it), then every ⚙ ``notifications.payment_reminder_repeat_days``.
  Compulsory for the shop; staff with ``credit.manage`` can pause them per shop.
- Handover reminders (item 11): collections still with a salesman after ⚙
  ``notifications.handover_reminder_days`` days, one digest per salesman.
- GST rate changes (item 12): products whose rate changes in 7 days."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.templatetags.documents import day, rate, rupees
from apps.notifications import consumer, delivery
from apps.notifications.context import EventContext, current_tenant, distributor_name, listing
from apps.notifications.models import ReminderPause
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from common.errors import InvalidFields, NotFound

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
        if late:
            note = f"{rupees(overdue)} overdue since {day(min(d.due_date for d in late))}"
        else:
            note = f"due on {day(oldest)}"
        ctx = EventContext(
            "payment.reminder",
            {
                "shop": shop.shop_name,
                "bills": f"{len(dues)} bill" + ("s" if len(dues) != 1 else ""),
                "amount": rupees(total),
                "overdue": rupees(overdue),
                "due_note": note,
            },
            retailer=shop,
            salesperson_id=shop.salesperson_id,
            shop_path="/shop/invoices",
            staff_path=f"/manage/retailers/{shop.pk}/ledger",
            extra={"paused": active_pause(shop.pk, today) is not None},
        )
        notify(job_event_id(shop.tenant_id, "payment.reminder", shop.pk, today), ctx)
        reminded += 1
    return reminded


def pause_reminders(
    retailer_id: UUID, *, reason: str, until: date | None, by: User
) -> ReminderPause:
    """Stop payment reminders for one shop (``credit.manage``), until a date or until resumed."""
    from common.dates import today_ist

    if not reason.strip():
        raise InvalidFields({"reason": ["Say why reminders are paused."]})
    if until is not None and until < today_ist():
        raise InvalidFields({"until": ["Choose today or a later date."]})
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
        ctx = EventContext(
            "handover.reminder",
            {
                "salesman": names.get(salesman) or "A salesman",
                "count": str(row["count"]),
                "amount": rupees(row["amount"]),
                "oldest": day(row["oldest"]),
            },
            collector_id=salesman,
            staff_path="/manage/payments/handover",
        )
        notify(job_event_id(tenant_id, "handover.reminder", salesman, today), ctx)
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
            "count": str(len(changes)),
            "change_date": day(target),
            "products": listing(
                [f"{c.product} ({rate(c.old_rate)} → {rate(c.new_rate)})" for c in changes]
            ),
        },
        staff_path="/manage/products",
    )
    notify(job_event_id(current_tenant().pk, "tax.rate_change_upcoming", target), ctx)
    return len(changes)
