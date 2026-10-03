"""Retailer writes (spec 5.5, PLAN §2.6). A retailer always comes with its sign-in login (the
mobile number); every change is audited, credit and blocking changes separately."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import Membership, User
from apps.accounts.tokens import revoke_all_refresh_tokens
from apps.audit import services as audit
from apps.ledger.models import RetailerAccount
from apps.platform.gst import gstin_problem
from apps.platform.models import State
from apps.platform.selectors import get_setting
from apps.platform.validators import normalize_gstin
from apps.pricing.models import PriceList
from apps.retailers.models import Retailer, RetailerAddress, RetailerUser
from common import languages
from common.errors import InvalidFields, NotFound
from common.numbers import fill
from common.phone import normalize_indian_mobile
from common.sequences import next_value
from common.tenancy import require_tenant_id

PROFILE_FIELDS = (
    "shop_name",
    "owner_name",
    "mobile",
    "email",
    "gstin",
    "state_id",
    "salesperson_id",
    "price_list_id",
    "notes",
    "tags",
    "preferred_language",
)
CREDIT_FIELDS = ("credit_limit", "payment_terms_days")
ADDRESS_FIELDS = ("label", "line1", "line2", "city", "district", "pincode", "state_id")


@dataclass(frozen=True)
class AddressInput:
    line1: str
    city: str
    pincode: str
    state_id: str
    line2: str = ""
    district: str = ""
    label: str = ""


def _retailer(retailer_id: UUID, *, lock: bool = False) -> Retailer:
    qs = Retailer.objects.filter(pk=retailer_id, deleted_at__isnull=True)
    found: Retailer | None = (qs.select_for_update() if lock else qs).first()
    if found is None:
        raise NotFound()
    return found


def _clean_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        tag = " ".join(str(tag).split()).lower()[:40]
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:20]


def _check_gstin(retailer: Retailer, errors: dict[str, list[str]]) -> None:
    """Registered shops: a valid GSTIN in use, matching the state; the PAN follows it."""
    retailer.gstin = normalize_gstin(retailer.gstin)
    problem = gstin_problem(retailer.gstin)
    if problem:
        errors.setdefault("gstin", []).append(problem)
        return
    retailer.pan = retailer.gstin[2:12]
    if not retailer.state_id:
        retailer.state_id = retailer.gstin[:2]
    elif retailer.state_id != retailer.gstin[:2]:
        errors.setdefault("state", []).append(
            fill(
                _("The state must match the first 2 digits of the GSTIN (%(value)s)."),
                {"value": retailer.gstin[:2]},
            )
        )
    clash = Retailer.objects.filter(gstin=retailer.gstin, deleted_at__isnull=True)
    if clash.exclude(pk=retailer.pk).exists():
        errors.setdefault("gstin", []).append(_("Another shop already has this GSTIN."))


def _check_mobile(retailer: Retailer, errors: dict[str, list[str]]) -> None:
    try:
        retailer.mobile = normalize_indian_mobile(retailer.mobile)
    except DjangoValidationError:
        errors.setdefault("mobile", []).append(_("Enter a 10-digit Indian mobile number."))
        return
    clash = Retailer.objects.filter(mobile=retailer.mobile, deleted_at__isnull=True)
    if clash.exclude(pk=retailer.pk).exists():
        errors.setdefault("mobile", []).append(_("Another shop already uses this mobile number."))


def _check_profile(retailer: Retailer, errors: dict[str, list[str]]) -> None:
    """Profile rules, reported per field in plain words."""
    if not retailer.shop_name.strip():
        errors.setdefault("shop_name", []).append(_("Enter the shop name."))
    _check_mobile(retailer, errors)
    if retailer.gstin:
        _check_gstin(retailer, errors)
    else:
        retailer.gstin, retailer.pan = None, ""  # an unregistered shop
    if (
        not retailer.state_id
        or not State.objects.filter(code=retailer.state_id, is_active=True).exists()
    ):
        errors.setdefault("state", []).append(_("Choose the shop's state."))
    if retailer.salesperson_id and not _is_staff(retailer.salesperson_id):
        errors.setdefault("salesperson", []).append(_("Choose an active staff member."))
    if retailer.preferred_language and not languages.is_known(retailer.preferred_language):
        # Empty: the distributor's default for shops (ADR-060).
        errors.setdefault("preferred_language", []).append(
            fill(_("Choose one of: %(languages)s."), {"languages": ", ".join(languages.codes())})
        )
    if (
        retailer.price_list_id
        and not PriceList.objects.filter(
            pk=retailer.price_list_id, deleted_at__isnull=True
        ).exists()
    ):
        errors.setdefault("price_list", []).append(_("Choose an existing price list."))


def _is_staff(user_id: UUID) -> bool:
    return Membership.objects.filter(user_id=user_id, is_active=True).exists()


def _check_credit(retailer: Retailer, errors: dict[str, list[str]]) -> None:
    if retailer.credit_limit is not None and retailer.credit_limit < 0:
        errors.setdefault("credit_limit", []).append(
            _("Enter 0 or more (leave it empty for no limit).")
        )
    if not 0 <= int(retailer.payment_terms_days) <= 365:
        errors.setdefault("payment_terms_days", []).append(_("Enter 0 to 365 days."))


def _address(
    retailer: Retailer, kind: str, data: AddressInput, *, default: bool
) -> RetailerAddress:
    address = RetailerAddress(
        retailer=retailer,
        kind=kind,
        is_default=default,
        label=data.label.strip()[:60],
        line1=data.line1.strip(),
        line2=data.line2.strip(),
        city=data.city.strip(),
        district=data.district.strip(),
        pincode=data.pincode.strip(),
        state_id=data.state_id,
    )
    _check_address(address)
    address.save()
    return address


def _check_address(address: RetailerAddress) -> None:
    errors: dict[str, list[str]] = {}
    if not address.line1:
        errors["line1"] = [_("Enter the address.")]
    if not address.city:
        errors["city"] = [_("Enter the city.")]
    if not (address.pincode.isdigit() and len(address.pincode) == 6 and address.pincode[0] != "0"):
        errors["pincode"] = [_("Enter a 6-digit PIN code.")]
    if not State.objects.filter(code=address.state_id, is_active=True).exists():
        errors["state"] = [_("Choose a state.")]
    if errors:
        raise InvalidFields(errors)


def _login(retailer: Retailer, *, by: User | None) -> User:
    """The RETAILER sign-in for the retailer's mobile. A number that belonged to a deleted shop
    keeps its login, which moves to the new shop."""
    tenant_id = require_tenant_id()
    user: User | None = User.objects.filter(
        user_type=User.UserType.RETAILER, tenant_id=tenant_id, phone=retailer.mobile
    ).first()
    if user is None:
        user = User.objects.create_user(
            None,
            None,
            user_type=User.UserType.RETAILER,
            phone=retailer.mobile,
            tenant_id=tenant_id,
            full_name=retailer.owner_name,
        )
    else:
        user.is_active, user.full_name = True, retailer.owner_name or user.full_name
        user.save(update_fields=["is_active", "full_name"])
    link = RetailerUser.objects.filter(user=user).first()
    if link is None:
        RetailerUser.objects.create(retailer=retailer, user=user, created_by=by)
    else:
        link.retailer = retailer
        link.save(update_fields=["retailer", "updated_at"])
    return user


@transaction.atomic
def create_retailer(
    *,
    shop_name: str,
    phone: str,
    contact_name: str = "",
    created_by: User | None = None,
    state_id: str | None = None,
    email: str = "",
    gstin: str | None = None,
    billing: AddressInput | None = None,
    extra: dict[str, Any] | None = None,
    send_welcome: bool = True,
) -> Retailer:
    """A retailer with its login; the welcome message goes out after commit."""
    tenant_id = require_tenant_id()
    from apps.platform.models import Tenant

    default_state = Tenant.objects.filter(pk=tenant_id).values_list("state_id", flat=True).first()
    # An unregistered shop defaults to the distributor's state; a GSTIN decides it otherwise.
    state = state_id or (None if gstin else default_state)
    retailer = Retailer(
        shop_name=" ".join(shop_name.split()),
        owner_name=" ".join(contact_name.split()),
        mobile=phone,
        email=email.strip().lower(),
        gstin=gstin or None,
        **({"state_id": state} if state else {}),
        payment_terms_days=int(get_setting("invoicing.default_payment_terms_days", tenant_id)),
        created_by=created_by,
    )
    for key, value in (extra or {}).items():
        setattr(retailer, key, value)
    retailer.tags = _clean_tags(retailer.tags or [])
    errors: dict[str, list[str]] = {}
    _check_profile(retailer, errors)
    _check_credit(retailer, errors)
    if errors:
        raise InvalidFields(errors)
    retailer.code = f"R-{next_value('retailer_code', 'all'):05d}"
    try:
        with transaction.atomic():
            retailer.save()
    except IntegrityError as exc:
        raise InvalidFields(
            {"mobile": [_("Another shop already uses this mobile number.")]}
        ) from exc
    RetailerAccount.objects.create(retailer=retailer)  # the per-shop lock (ADR-044)
    _login(retailer, by=created_by)
    if billing is not None:
        _address(retailer, RetailerAddress.Kind.BILLING, billing, default=True)
    audit.record(
        "retailer.created",
        target=retailer,
        target_repr=f"{retailer.code} {retailer.shop_name}",
        metadata={"mobile_tail": retailer.mobile[-4:]},
    )
    if send_welcome:
        _queue_welcome(retailer)
    return retailer


def _queue_welcome(retailer: Retailer) -> None:
    from apps.retailers.tasks import send_retailer_welcome

    retailer_id, tenant_id = str(retailer.pk), str(require_tenant_id())
    transaction.on_commit(
        lambda: send_retailer_welcome.delay(retailer_id=retailer_id, tenant_id=tenant_id)
    )


@transaction.atomic
def update_retailer(retailer_id: UUID, changes: dict[str, Any], *, by: User) -> Retailer:
    retailer = _retailer(retailer_id, lock=True)
    before = {f: getattr(retailer, f) for f in PROFILE_FIELDS}
    for key in PROFILE_FIELDS:
        if key in changes:
            value = changes[key]
            if key in ("shop_name", "owner_name"):
                value = " ".join(str(value).split())
            elif key == "email":
                value = (value or "").strip().lower()
            elif key == "tags":
                value = _clean_tags(value)
            setattr(retailer, key, value)
    errors: dict[str, list[str]] = {}
    _check_profile(retailer, errors)
    if errors:
        raise InvalidFields(errors)
    diff = audit.diff(before, {f: getattr(retailer, f) for f in PROFILE_FIELDS})
    if not diff:
        return retailer
    retailer.save()
    if "mobile" in diff or "owner_name" in diff:
        _move_login(retailer)
    audit.record(
        "retailer.updated",
        target=retailer,
        target_repr=f"{retailer.code} {retailer.shop_name}",
        changes=diff,
    )
    return retailer


def _move_login(retailer: Retailer) -> None:
    """The sign-in follows the shop's mobile number; old sessions end."""
    link = RetailerUser.objects.select_related("user").filter(retailer=retailer).first()
    if link is None:
        _login(retailer, by=None)
        return
    user = link.user
    if user.phone != retailer.mobile:
        taken = User.objects.filter(
            user_type=User.UserType.RETAILER, tenant_id=retailer.tenant_id, phone=retailer.mobile
        ).exclude(pk=user.pk)
        if taken.exists():
            raise InvalidFields(
                {"mobile": [_("This number was used by a deleted shop. Ask support to free it.")]}
            )
        user.phone = retailer.mobile
        revoke_all_refresh_tokens(user)
    user.full_name = retailer.owner_name
    user.save(update_fields=["phone", "full_name"])


@transaction.atomic
def update_credit(
    retailer_id: UUID, *, credit_limit: Decimal | None, payment_terms_days: int, by: User
) -> Retailer:
    """Credit limit (empty = no limit, 0 = no credit; PLAN C2) and payment terms (audited)."""
    retailer = _retailer(retailer_id, lock=True)
    before = {f: getattr(retailer, f) for f in CREDIT_FIELDS}
    retailer.credit_limit, retailer.payment_terms_days = credit_limit, payment_terms_days
    errors: dict[str, list[str]] = {}
    _check_credit(retailer, errors)
    if errors:
        raise InvalidFields(errors)
    diff = audit.diff(before, {f: getattr(retailer, f) for f in CREDIT_FIELDS})
    if diff:
        retailer.save(update_fields=[*CREDIT_FIELDS, "updated_at"])
        audit.record(
            "retailer.credit_changed",
            target=retailer,
            target_repr=f"{retailer.code} {retailer.shop_name}",
            changes=diff,
        )
    return retailer


@transaction.atomic
def block_retailer(retailer_id: UUID, *, reason: str, by: User) -> Retailer:
    """On hold (ADR-036): ordering stops (Phase 4); sign-in follows
    ``retailers.blocked_can_sign_in``."""
    if not reason.strip():
        raise InvalidFields({"reason": [_("Enter why this shop is put on hold.")]})
    retailer = _retailer(retailer_id, lock=True)
    if retailer.status == Retailer.Status.BLOCKED:
        return retailer
    retailer.status, retailer.blocked_reason = Retailer.Status.BLOCKED, reason.strip()[:300]
    retailer.save(update_fields=["status", "blocked_reason", "updated_at"])
    audit.record(
        "retailer.blocked",
        target=retailer,
        target_repr=f"{retailer.code} {retailer.shop_name}",
        changes={"status": ["ACTIVE", "BLOCKED"]},
        metadata={"reason": retailer.blocked_reason},
    )
    return retailer


@transaction.atomic
def unblock_retailer(retailer_id: UUID, *, by: User) -> Retailer:
    retailer = _retailer(retailer_id, lock=True)
    if retailer.status == Retailer.Status.ACTIVE:
        return retailer
    retailer.status, retailer.blocked_reason = Retailer.Status.ACTIVE, ""
    retailer.save(update_fields=["status", "blocked_reason", "updated_at"])
    audit.record(
        "retailer.unblocked",
        target=retailer,
        target_repr=f"{retailer.code} {retailer.shop_name}",
        changes={"status": ["BLOCKED", "ACTIVE"]},
    )
    return retailer


@transaction.atomic
def delete_retailer(retailer_id: UUID, *, by: User) -> None:
    """Soft delete; the login stops at once. PHASE 4/5: refuse while orders are open or a balance
    is outstanding (PLAN §3.6)."""
    retailer = _retailer(retailer_id, lock=True)
    retailer.deleted_at, retailer.is_active = timezone.now(), False
    retailer.save(update_fields=["deleted_at", "is_active", "updated_at"])
    for link in RetailerUser.objects.select_related("user").filter(retailer=retailer):
        link.user.is_active = False
        link.user.save(update_fields=["is_active"])
        revoke_all_refresh_tokens(link.user)
    audit.record(
        "retailer.deleted", target=retailer, target_repr=f"{retailer.code} {retailer.shop_name}"
    )


@transaction.atomic
def resend_welcome(retailer_id: UUID, *, by: User) -> None:
    retailer = _retailer(retailer_id)
    audit.record(
        "retailer.welcome_resent",
        target=retailer,
        target_repr=f"{retailer.code} {retailer.shop_name}",
    )
    _queue_welcome(retailer)


def send_welcome(retailer_id: str) -> None:
    """Runs in a task (tenant set): the welcome SMS as a notification (ADR-048 item 15: logged,
    retried by the delivery, never switched off). Each call is a new message (a resend)."""
    from uuid import uuid4

    from apps.notifications.context import EventContext
    from apps.notifications.jobs import notify
    from common.tenancy import tenant_transaction

    with tenant_transaction(require_tenant_id()):
        retailer = Retailer.objects.filter(pk=retailer_id, deleted_at__isnull=True).first()
        if retailer is None:
            return
        ctx = EventContext(
            "retailer.welcome", {"shop": retailer.shop_name}, retailer=retailer,
            shop_path="/shop/login",
        )  # fmt: skip
        notify(uuid4(), ctx)
        Retailer.objects.filter(pk=retailer_id).update(welcome_sent_at=timezone.now())


# --- Addresses ----------------------------------------------------------------------------------


@transaction.atomic
def save_address(
    retailer_id: UUID,
    address_id: UUID | None,
    *,
    kind: str,
    data: dict[str, Any],
    is_default: bool | None,
    by: User,
) -> RetailerAddress:
    retailer = _retailer(retailer_id, lock=True)
    if kind not in RetailerAddress.Kind.values:
        raise InvalidFields({"kind": [_("Choose billing or shipping.")]})
    if address_id is None:
        address = RetailerAddress(retailer=retailer, kind=kind, created_by=by)
        first = not RetailerAddress.objects.filter(retailer=retailer, kind=kind).exists()
        address.is_default = True if first else bool(is_default)
    else:
        found = RetailerAddress.objects.filter(pk=address_id, retailer=retailer).first()
        if found is None:
            raise NotFound()
        address = found
        address.kind = kind
        if is_default is not None:
            address.is_default = is_default
    for key in ADDRESS_FIELDS:
        if key in data:
            setattr(address, key, str(data[key]).strip())
    if "distance_km" in data:  # for e-way bills (Phase 7); left out: unchanged
        address.distance_km = data["distance_km"]
    _check_address(address)
    if address.is_default:
        RetailerAddress.objects.filter(
            retailer=retailer, kind=address.kind, is_default=True
        ).exclude(pk=address.pk).update(is_default=False)
    address.save()
    audit.record(
        "retailer.address_saved",
        target=retailer,
        target_repr=f"{retailer.code} {retailer.shop_name}",
        metadata={"kind": address.kind, "address_id": str(address.pk)},
    )
    return address


@transaction.atomic
def delete_address(retailer_id: UUID, address_id: UUID, *, by: User) -> None:
    retailer = _retailer(retailer_id, lock=True)
    address = RetailerAddress.objects.filter(pk=address_id, retailer=retailer).first()
    if address is None:
        raise NotFound()
    kind, was_default = address.kind, address.is_default
    address.delete()
    if was_default:  # another address of the same kind becomes the default
        replacement = RetailerAddress.objects.filter(retailer=retailer, kind=kind).first()
        if replacement is not None:
            replacement.is_default = True
            replacement.save(update_fields=["is_default", "updated_at"])
    audit.record(
        "retailer.address_deleted",
        target=retailer,
        target_repr=f"{retailer.code} {retailer.shop_name}",
        metadata={"kind": kind},
    )


# --- Bulk -------------------------------------------------------------------------------------

BULK_ACTIONS = ("assign_salesperson", "assign_price_list", "block", "unblock")


def _bulk_price_list(retailer: Retailer, price_list: UUID | None, by: User) -> bool:
    if retailer.price_list_id == price_list:
        return False
    audit.record(
        "retailer.updated",
        target=retailer,
        target_repr=f"{retailer.code} {retailer.shop_name}",
        changes={"price_list_id": [str(retailer.price_list_id or ""), str(price_list or "")]},
    )
    retailer.price_list_id = price_list
    retailer.save(update_fields=["price_list", "updated_at"])
    return True


def _bulk_salesperson(retailer: Retailer, salesperson: UUID | None) -> bool:
    if retailer.salesperson_id == salesperson:
        return False
    retailer.salesperson_id = salesperson
    retailer.save(update_fields=["salesperson", "updated_at"])
    return True


@transaction.atomic
def bulk_update(
    retailer_ids: list[UUID], action: str, *, value: str | None = None, by: User
) -> int:
    if action not in BULK_ACTIONS:
        raise InvalidFields({"action": [_("Choose a supported action.")]})
    if not retailer_ids or len(retailer_ids) > 1000:
        raise InvalidFields({"retailer_ids": [_("Select 1 to 1,000 shops.")]})
    salesperson = UUID(value) if action == "assign_salesperson" and value else None
    if salesperson and not _is_staff(salesperson):
        raise InvalidFields({"value": [_("Choose an active staff member.")]})
    price_list = UUID(value) if action == "assign_price_list" and value else None
    if price_list and not PriceList.objects.filter(pk=price_list, deleted_at__isnull=True).exists():
        raise InvalidFields({"value": [_("Choose an existing price list.")]})
    retailers = list(
        Retailer.objects.filter(pk__in=retailer_ids, deleted_at__isnull=True).select_for_update()
    )
    changed = 0
    for retailer in retailers:
        if action == "assign_salesperson":
            changed += _bulk_salesperson(retailer, salesperson)
        elif action == "assign_price_list":
            changed += _bulk_price_list(retailer, price_list, by)
        elif action == "block" and retailer.status != Retailer.Status.BLOCKED:
            block_retailer(retailer.pk, reason=value or "Put on hold in bulk", by=by)
            changed += 1
        elif action == "unblock" and retailer.status != Retailer.Status.ACTIVE:
            unblock_retailer(retailer.pk, by=by)
            changed += 1
    audit.record(
        "retailers.bulk_updated",
        target_type="retailers.retailer",
        metadata={
            "action": action,
            "value": value,
            "count": changed,
            "retailer_ids": [str(r.pk) for r in retailers][:200],
        },
    )
    return changed
