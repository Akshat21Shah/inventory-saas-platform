"""Reorder suggestions (ADR-053 item 8), worked out with the stats (nightly and on demand).

- d: daily demand (``ProductStats.per_day``). Position = available + on order - waiting
  (shops' backorders). Lead time: the preferred supplier's time for the product, else the
  supplier's usual time, else ⚙ ``planning.default_lead_days``.
- Reorder point = d x lead time + safety stock (⚙ ``planning.safety_days`` of demand). At or below
  it, order d x (lead time + ⚙ ``planning.cover_days``) + safety stock - position.
- Little or no history (nothing ordered in the demand period): only when shops are waiting or
  stock is at or below the product's own reorder level, ordering up to that level plus what is
  waiting. A dead product (in stock, not sold in the classification period) below its level with
  no shop waiting is not suggested: it is kept apart as NOT_SELLING, so staff can lower the level.
- Days left: whole days, rounded down (urgency first).
- Reorder points and quantities round up: whole numbers for units that can't be split, 2 decimals
  otherwise; a quantity then goes up to the preferred supplier's pack (``quantities``).
- Staff change the quantity, dismiss for a while, put suggestions on purchase orders (grouped by
  preferred supplier) or use the reorder point as the product's reorder level (never automatic).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.catalog.selectors import ProductFilters
from apps.catalog.selectors import product_list as catalog_products
from apps.inventory import selectors as stock
from apps.planning.models import MovementClass, ProductStats, ReorderSuggestion
from apps.planning.quantities import up, up_to_pack
from apps.platform.selectors import get_setting, is_feature_enabled
from common.dates import today_ist
from common.errors import InvalidFields, NotFound
from common.tenancy import require_tenant_id

ZERO = Decimal("0")
QTY = Decimal("0.001")
TENTH = Decimal("0.1")
S = ReorderSuggestion.Status
DISMISS_DAYS = 7


@dataclass(frozen=True)
class _Lead:
    days: int
    source: str
    supplier_id: UUID | None
    pack: Decimal | None


def _leads(default_days: int) -> dict[UUID, _Lead]:
    """Each product's preferred supplier, its delivery time and pack (purchasing on only)."""
    if not is_feature_enabled("purchasing"):
        return {}
    from apps.purchasing.models import SupplierProduct

    links = SupplierProduct.objects.filter(
        is_preferred=True, supplier__deleted_at__isnull=True, supplier__is_active=True
    ).select_related("supplier")
    out = {}
    for link in links:
        if link.lead_time_days:
            days, source = link.lead_time_days, ReorderSuggestion.LeadSource.PRODUCT_SUPPLIER
        elif link.supplier.lead_time_days:
            days, source = link.supplier.lead_time_days, ReorderSuggestion.LeadSource.SUPPLIER
        else:
            days, source = default_days, ReorderSuggestion.LeadSource.DEFAULT
        out[link.product_id] = _Lead(days, source, link.supplier_id, link.pack_size)
    return out


def refresh_suggestions(*, today: date | None = None) -> int:
    """Work out the active distributor's open suggestions (after the stats); returns how many
    are open."""
    tenant = require_tenant_id()
    today = today or today_ist()
    safety_days = int(get_setting("planning.safety_days", tenant))
    cover_days = int(get_setting("planning.cover_days", tenant))
    default_lead = int(get_setting("planning.default_lead_days", tenant))
    demand_days = int(get_setting("planning.demand_days", tenant))
    stats = {s.product_id: s for s in ProductStats.objects.all()}
    leads = _leads(default_lead)
    on_order: dict[UUID, Any] = {}
    if is_feature_enabled("purchasing"):
        from apps.purchasing.selectors import on_order as purchasing_on_order

        on_order = purchasing_on_order()
    resting = set(
        ReorderSuggestion.objects.filter(status=S.DISMISSED, dismissed_until__gt=today).values_list(
            "product_id", flat=True
        )
    )
    annotated: Any = stock.with_stock(catalog_products(ProductFilters()).filter(is_active=True))
    listed = annotated.values(
        "id", "available", "backordered", "reorder_level", "unit__allows_decimal"
    )
    now = timezone.now()
    wanted: dict[UUID, dict[str, Any]] = {}
    for row in listed:
        pk = row["id"]
        if pk in resting:
            continue
        found = stats.get(pk)
        d = found.per_day if found else ZERO
        lead = leads.get(pk) or _Lead(
            default_lead, ReorderSuggestion.LeadSource.DEFAULT, None, None
        )
        available, waiting = row["available"], row["backordered"]
        ordered = on_order[pk].quantity if pk in on_order else ZERO
        position = available + ordered - waiting
        whole = not row["unit__allows_decimal"]
        safety = d * safety_days
        point = up(d * lead.days + safety, whole)
        level = row["reorder_level"] or ZERO
        if d > 0:
            basis = ReorderSuggestion.Basis.DEMAND
            needed = position <= point
            quantity = d * (lead.days + cover_days) + safety - position
        else:
            basis = ReorderSuggestion.Basis.LOW_HISTORY
            needed = waiting > 0 or (level > 0 and available <= level)
            quantity = level + waiting - available - ordered
        if not needed or quantity <= 0:
            continue
        dead = found is not None and found.movement_class == MovementClass.DEAD
        not_selling = basis == ReorderSuggestion.Basis.LOW_HISTORY and dead and waiting <= 0
        wanted[pk] = {
            "status": S.NOT_SELLING if not_selling else S.OPEN,
            "last_sale_date": found.last_sale_date if found else None,
            "supplier_id": lead.supplier_id,
            "computed_at": now,
            "basis": basis,
            "demand_qty": found.demand_qty if found else ZERO,
            "demand_days": found.demand_days if found else demand_days,
            "per_day": d,
            "available": available,
            "on_order": ordered,
            "waiting": waiting,
            "reorder_level": level,
            "lead_days": lead.days,
            "lead_source": lead.source,
            "safety_days": safety_days,
            "cover_days": cover_days,
            "reorder_point": point,
            "pack_size": lead.pack,
            "suggested_qty": up_to_pack(quantity, lead.pack, whole),
            "days_left": Decimal(int(max(available, ZERO) / d)).quantize(TENTH) if d > 0 else None,
        }
    with transaction.atomic():
        open_rows = {
            s.product_id: s
            for s in ReorderSuggestion.objects.select_for_update().filter(
                status__in=[S.OPEN, S.NOT_SELLING]
            )
        }
        for pk, row in open_rows.items():
            if pk not in wanted:
                row.status = S.RESOLVED
                row.save(update_fields=["status", "updated_at"])
        for pk, values in wanted.items():
            existing = open_rows.get(pk)
            if existing is None:
                ReorderSuggestion.objects.create(product_id=pk, **values)
                continue
            for field, value in values.items():
                setattr(existing, field, value)
            if existing.status == S.NOT_SELLING:
                existing.quantity = None
            existing.save()  # a quantity staff changed stays while it is to order
    return sum(1 for values in wanted.values() if values["status"] == S.OPEN)


# --- What staff do with them ------------------------------------------------------------------


def _open(suggestion_id: UUID) -> ReorderSuggestion:
    found: ReorderSuggestion | None = (
        ReorderSuggestion.objects.select_for_update()
        .filter(pk=suggestion_id, status=S.OPEN)
        .first()
    )
    if found is None:
        raise NotFound()
    return found


@transaction.atomic
def change_quantity(
    suggestion_id: UUID, quantity: Decimal | None, *, by: User
) -> ReorderSuggestion:
    """``None`` goes back to the suggested quantity."""
    suggestion = _open(suggestion_id)
    if quantity is not None and (quantity <= 0 or quantity != quantity.quantize(QTY)):
        raise InvalidFields({"quantity": [_("Enter a quantity above 0, with at most 3 decimals.")]})
    unit = suggestion.product.unit
    if quantity is not None and not unit.allows_decimal and quantity != quantity.to_integral():
        raise InvalidFields(
            {"quantity": [_("%(code)s is counted in whole numbers.") % {"code": unit.code}]}
        )
    suggestion.quantity = quantity
    suggestion.save(update_fields=["quantity", "updated_at"])
    return suggestion


@transaction.atomic
def dismiss(suggestion_id: UUID, *, until: date | None, by: User) -> ReorderSuggestion:
    """Not suggested again until ``until`` (a week by default)."""
    today = today_ist()
    until = until or today + timedelta(days=DISMISS_DAYS)
    if until <= today:
        raise InvalidFields({"until": [_("Choose a date after today.")]})
    suggestion = _open(suggestion_id)
    suggestion.status = S.DISMISSED
    suggestion.dismissed_by, suggestion.dismissed_at = by, timezone.now()
    suggestion.dismissed_until = until
    suggestion.save()
    audit.record(
        "planning.suggestion_dismissed",
        target=suggestion.product,
        target_repr=f"{suggestion.product.code} {suggestion.product.name}",
        metadata={"until": until.isoformat()},
    )
    return suggestion


def _chosen(ids: Sequence[UUID]) -> list[ReorderSuggestion]:
    if not ids or len(ids) > 500:
        raise InvalidFields({"suggestion_ids": [_("Choose 1 to 500 suggestions.")]})
    rows = list(
        ReorderSuggestion.objects.select_for_update()
        .filter(pk__in=ids, status=S.OPEN)
        .select_related("product", "product__unit")
        .order_by("product__code")
    )
    if len(rows) != len(set(ids)):
        raise InvalidFields(
            {"suggestion_ids": [_("Some suggestions are no longer open. Refresh.")]}
        )
    return rows


@transaction.atomic
def create_orders(ids: Sequence[UUID], *, by: User) -> list[Any]:
    """Draft purchase orders, one per preferred supplier, with the quantities to order."""
    from apps.purchasing import orders

    rows = _chosen(ids)
    without = [row.product.code for row in rows if row.supplier_id is None]
    if without:
        raise InvalidFields(
            {
                "suggestion_ids": [
                    _("Choose a preferred supplier first for: %(without)s.")
                    % {"without": ", ".join(without)}
                ]
            }
        )
    by_supplier: dict[UUID, list[ReorderSuggestion]] = defaultdict(list)
    for row in rows:
        assert row.supplier_id is not None
        by_supplier[row.supplier_id].append(row)
    created = []
    for supplier_id, group in by_supplier.items():
        order = orders.create_order(
            orders.OrderInput(
                supplier_id=supplier_id,
                lines=[orders.OrderLineInput(row.product_id, row.to_order) for row in group],
            ),
            by=by,
        )
        lines = {line.product_id: line for line in order.lines.all()}
        for row in group:
            row.status = S.ORDERED
            row.purchase_order_line = lines[row.product_id]
            row.save(update_fields=["status", "purchase_order_line", "updated_at"])
        created.append(order)
    return created


@transaction.atomic
def apply_reorder_levels(ids: Sequence[UUID], *, by: User) -> int:
    """Use each suggestion's reorder point as its product's reorder level (audited per product;
    whole units where the unit is counted in whole numbers). Returns how many changed."""
    from apps.inventory.adjustments import set_reorder_level

    changed = 0
    for row in _chosen(ids):
        level = up(row.reorder_point, not row.product.unit.allows_decimal)
        if level <= 0 or level == row.product.reorder_level:
            continue
        set_reorder_level(row.product_id, level, by=by)
        changed += 1
    return changed
