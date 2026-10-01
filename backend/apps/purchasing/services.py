"""Suppliers and the products they supply (ADR-053 item 4). Every change is audited."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.catalog.models import Product
from apps.inventory.models import StockInward
from apps.platform.gst import gstin_problem
from apps.platform.models import State
from apps.platform.validators import normalize_gstin
from apps.purchasing.models import Supplier, SupplierProduct
from apps.purchasing.selectors import name_key, unlinked_receipts
from common.errors import InvalidFields, NotFound
from common.sequences import next_value

PROFILE_FIELDS = (
    "name",
    "gstin",
    "state_id",
    "contact_name",
    "phone",
    "email",
    "address_line1",
    "address_line2",
    "city",
    "pincode",
    "payment_terms_days",
    "lead_time_days",
    "notes",
    "is_active",
)
PHONE = re.compile(r"\+?[0-9][0-9 ()-]{8,18}")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
BULK_LIMIT = 1000
MAX_LINKS = 20


def _clean(key: str, value: Any) -> Any:
    if key in ("name", "contact_name", "city", "address_line1", "address_line2"):
        return " ".join(str(value or "").split())
    if key == "gstin":
        return normalize_gstin(value) or None
    if key == "email":
        return (value or "").strip().lower()
    if key in ("phone", "pincode", "notes"):
        return (value or "").strip()
    return value


def _check(supplier: Supplier) -> None:
    errors: dict[str, list[str]] = {}
    if not supplier.name:
        errors["name"] = ["Enter the supplier's name."]
    if supplier.gstin:
        problem = gstin_problem(supplier.gstin)
        if problem:
            errors["gstin"] = [problem]
        else:
            taken = Supplier.objects.filter(gstin=supplier.gstin, deleted_at__isnull=True).exclude(
                pk=supplier.pk
            )
            if taken.exists():
                errors["gstin"] = ["Another supplier has this GSTIN."]
            elif supplier.state_id and supplier.state_id != supplier.gstin[:2]:
                errors["state_id"] = [
                    f"The state must match the first 2 digits of the GSTIN ({supplier.gstin[:2]})."
                ]
            supplier.state_id = supplier.gstin[:2]
    if supplier.state_id and not State.objects.filter(pk=supplier.state_id).exists():
        errors["state_id"] = ["Choose a state."]
    if supplier.phone and not PHONE.fullmatch(supplier.phone):
        errors["phone"] = ["Enter a phone number with 10 to 15 digits."]
    if supplier.email and not EMAIL.fullmatch(supplier.email):
        errors["email"] = ["Enter an email address."]
    if supplier.pincode and not re.fullmatch(r"[1-9][0-9]{5}", supplier.pincode):
        errors["pincode"] = ["Enter a 6-digit PIN code."]
    if not 0 <= supplier.payment_terms_days <= 365:
        errors["payment_terms_days"] = ["Enter 0 to 365 days."]
    if supplier.lead_time_days is not None and not 1 <= supplier.lead_time_days <= 365:
        errors["lead_time_days"] = ["Enter 1 to 365 days, or leave it empty."]
    if errors:
        raise InvalidFields(errors)


def _repr(supplier: Supplier) -> str:
    return f"{supplier.code} {supplier.name}"


@transaction.atomic
def create_supplier(data: dict[str, Any], *, by: User | None) -> Supplier:
    supplier = Supplier(**{k: _clean(k, v) for k, v in data.items() if k in PROFILE_FIELDS})
    _check(supplier)
    supplier.code = f"S-{next_value('supplier_code', 'all'):04d}"
    supplier.created_by = by
    supplier.save()
    audit.record("purchasing.supplier_created", target=supplier, target_repr=_repr(supplier))
    return supplier


def _supplier(supplier_id: UUID, *, lock: bool = False) -> Supplier:
    qs = Supplier.objects.filter(pk=supplier_id, deleted_at__isnull=True)
    found = (qs.select_for_update() if lock else qs).first()
    if found is None:
        raise NotFound()
    supplier: Supplier = found
    return supplier


@transaction.atomic
def update_supplier(supplier_id: UUID, changes: dict[str, Any], *, by: User) -> Supplier:
    supplier = _supplier(supplier_id, lock=True)
    before = {f: getattr(supplier, f) for f in PROFILE_FIELDS}
    for key, value in changes.items():
        if key in PROFILE_FIELDS:
            setattr(supplier, key, _clean(key, value))
    _check(supplier)
    diff = audit.diff(before, {f: getattr(supplier, f) for f in PROFILE_FIELDS})
    if diff:
        supplier.save()
        audit.record(
            "purchasing.supplier_changed",
            target=supplier,
            target_repr=_repr(supplier),
            changes=diff,
        )
    return supplier


@transaction.atomic
def delete_supplier(supplier_id: UUID, *, by: User) -> None:
    """Soft delete: it leaves pick lists and its product links go. Past receipts keep it.
    9a.5: refused while it has open purchase orders."""
    supplier = _supplier(supplier_id, lock=True)
    supplier.deleted_at, supplier.is_active = timezone.now(), False
    supplier.save(update_fields=["deleted_at", "is_active", "updated_at"])
    removed, _ = SupplierProduct.objects.filter(supplier=supplier).delete()
    audit.record(
        "purchasing.supplier_deleted",
        target=supplier,
        target_repr=_repr(supplier),
        metadata={"product_links_removed": removed},
    )


# --- What a product is bought from -------------------------------------------------------------


@dataclass(frozen=True)
class LinkInput:
    supplier_id: UUID
    is_preferred: bool = False
    supplier_code: str = ""
    lead_time_days: int | None = None
    pack_size: Decimal | None = None


def _product(product_id: UUID) -> Product:
    found = Product.objects.filter(pk=product_id, deleted_at__isnull=True).first()
    if found is None:
        raise NotFound()
    product: Product = found
    return product


@transaction.atomic
def set_product_suppliers(
    product_id: UUID, links: Sequence[LinkInput], *, by: User
) -> list[SupplierProduct]:
    """Replace who supplies a product. With any supplier, exactly one is preferred (the first,
    unless one is marked). Each keeps the last cost it was bought at."""
    product = _product(product_id)
    errors: dict[str, list[str]] = {}
    ids = [link.supplier_id for link in links]
    if len(links) > MAX_LINKS:
        errors["links"] = [f"A product can have up to {MAX_LINKS} suppliers."]
    if len(set(ids)) != len(ids):
        errors["links"] = ["List each supplier once."]
    if sum(link.is_preferred for link in links) > 1:
        errors["links"] = ["Choose one preferred supplier."]
    found = set(
        Supplier.objects.filter(pk__in=ids, deleted_at__isnull=True).values_list("pk", flat=True)
    )
    if set(ids) - found:
        errors["links"] = ["Choose your own active suppliers."]
    for link in links:
        if link.lead_time_days is not None and not 1 <= link.lead_time_days <= 365:
            errors["links"] = ["Enter a delivery time of 1 to 365 days, or leave it empty."]
        if link.pack_size is not None and link.pack_size <= 0:
            errors["links"] = ["A pack size must be above zero."]
    if errors:
        raise InvalidFields(errors)
    preferred = next((link.supplier_id for link in links if link.is_preferred), None)
    if preferred is None and links:
        preferred = links[0].supplier_id
    existing = {
        row.supplier_id: row
        for row in SupplierProduct.objects.select_for_update().filter(product=product)
    }
    before = {str(pk): _link_state(row) for pk, row in existing.items()}
    SupplierProduct.objects.filter(product=product).exclude(supplier_id__in=ids).delete()
    # Unmark the old preferred one first: one preferred per product (database constraint).
    SupplierProduct.objects.filter(product=product, is_preferred=True).exclude(
        supplier_id=preferred
    ).update(is_preferred=False)
    rows = []
    for link in links:
        row = existing.get(link.supplier_id) or SupplierProduct(
            product=product, supplier_id=link.supplier_id, created_by=by
        )
        row.is_preferred = link.supplier_id == preferred
        row.supplier_code = link.supplier_code.strip()
        row.lead_time_days = link.lead_time_days
        row.pack_size = link.pack_size
        row.save()
        rows.append(row)
    after = {str(row.supplier_id): _link_state(row) for row in rows}
    if before != after:
        audit.record(
            "purchasing.product_suppliers_changed",
            target=product,
            target_repr=f"{product.code} {product.name}",
            changes={"suppliers": [before, after]},
        )
    return rows


def _link_state(row: SupplierProduct) -> dict[str, Any]:
    return {
        "preferred": row.is_preferred,
        "code": row.supplier_code,
        "lead_time_days": row.lead_time_days,
        "pack_size": str(row.pack_size) if row.pack_size is not None else None,
    }


@transaction.atomic
def set_preferred_supplier(supplier_id: UUID, product_ids: Iterable[UUID], *, by: User) -> int:
    """Make this supplier the preferred one for many products (the products bulk action);
    returns how many changed."""
    supplier = _supplier(supplier_id)
    ids = list(dict.fromkeys(product_ids))
    if not ids or len(ids) > BULK_LIMIT:
        raise InvalidFields({"product_ids": [f"Select 1 to {BULK_LIMIT} products."]})
    products = list(
        Product.objects.filter(pk__in=ids, deleted_at__isnull=True)
        .order_by("pk")
        .select_for_update()
        .values_list("pk", flat=True)
    )
    already = set(
        SupplierProduct.objects.filter(
            supplier=supplier, product_id__in=products, is_preferred=True
        ).values_list("product_id", flat=True)
    )
    changing = [pk for pk in products if pk not in already]
    SupplierProduct.objects.filter(product_id__in=changing, is_preferred=True).update(
        is_preferred=False
    )
    linked = set(
        SupplierProduct.objects.filter(supplier=supplier, product_id__in=changing).values_list(
            "product_id", flat=True
        )
    )
    SupplierProduct.objects.filter(supplier=supplier, product_id__in=linked).update(
        is_preferred=True
    )
    SupplierProduct.objects.bulk_create(
        [
            SupplierProduct(
                tenant_id=supplier.tenant_id,
                supplier=supplier,
                product_id=pk,
                is_preferred=True,
                created_by=by,
            )
            for pk in changing
            if pk not in linked
        ]
    )
    audit.record(
        "purchasing.preferred_supplier_set",
        target=supplier,
        target_repr=_repr(supplier),
        metadata={"count": len(changing), "product_ids": [str(pk) for pk in changing][:200]},
    )
    return len(changing)


# --- Suppliers from past goods receipts (a one-time review) ------------------------------------


@dataclass(frozen=True)
class ReceiptSupplierChoice:
    name: str  # as listed (receipts with this name, ignoring case and extra spaces)
    supplier_id: UUID | None = None  # link them to this supplier, or
    create: bool = False  # make a new supplier with this name


@transaction.atomic
def confirm_receipt_suppliers(
    choices: Sequence[ReceiptSupplierChoice], *, by: User
) -> dict[str, int]:
    """Link past receipts to suppliers, as staff confirmed them on the review list. A receipt is
    linked once; its typed supplier name stays as it was."""
    errors: dict[str, list[str]] = {}
    for choice in choices:
        if not " ".join(choice.name.split()):
            errors["choices"] = ["Each row needs the supplier name from the receipts."]
        elif choice.create == (choice.supplier_id is not None):
            errors["choices"] = ["For each name, choose a supplier or create a new one."]
    if errors:
        raise InvalidFields(errors)
    created = linked = 0
    for choice in choices:
        name = " ".join(choice.name.split())
        if choice.create:
            supplier = create_supplier({"name": name}, by=by)
            created += 1
        else:
            supplier = _supplier(choice.supplier_id)  # type: ignore[arg-type]
        ids = [pk for pk, typed in unlinked_receipts() if name_key(typed) == name_key(name)]
        linked += StockInward.objects.filter(pk__in=ids, supplier__isnull=True).update(
            supplier=supplier
        )
    audit.record(
        "purchasing.receipt_suppliers_confirmed",
        target_type="purchasing.supplier",
        metadata={"names": len(choices), "suppliers_created": created, "receipts_linked": linked},
    )
    return {"suppliers_created": created, "receipts_linked": linked}
