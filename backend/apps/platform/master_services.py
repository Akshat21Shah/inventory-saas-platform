"""Platform master data (super admin): plans, feature flag catalogue, GST rates, cess types and
HSN rate hints (PLAN §3.3, §9.2). Every change is audited as a platform-level entry."""

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.utils.translation import gettext

from apps.accounts.models import User
from apps.audit import services as audit
from apps.platform.models import CessType, FeatureFlag, HsnRateHint, Plan, TaxRate
from apps.platform.selectors import invalidate_all_features
from apps.platform.validators import validate_hsn_prefix
from common.errors import InvalidFields, NotFound

HSN_IMPORT_MAX_BYTES = 1_000_000
HSN_IMPORT_MAX_ROWS = 20_000


def _get(model: type[models.Model], **lookup: Any) -> Any:
    obj = model._default_manager.select_for_update().filter(**lookup).first()
    if obj is None:
        raise NotFound()
    return obj


def _save_changed(
    obj: models.Model, changes: dict[str, Any], fields: tuple[str, ...], action: str
) -> dict[str, list[Any]]:
    before = {f: getattr(obj, f) for f in fields}
    for field, value in changes.items():
        if field in fields:
            setattr(obj, field, value)
    try:
        obj.full_clean()
    except DjangoValidationError as exc:
        raise InvalidFields({k: [str(m) for m in v] for k, v in exc.message_dict.items()}) from exc
    diff = audit.diff(before, {f: getattr(obj, f) for f in fields})
    if diff:
        obj.save()
        audit.record(action, target=obj, tenant_id=None, changes=diff)
    return diff


def _create(obj: models.Model, action: str) -> Any:
    try:
        obj.full_clean()
    except DjangoValidationError as exc:
        raise InvalidFields({k: [str(m) for m in v] for k, v in exc.message_dict.items()}) from exc
    obj.save(force_insert=True)
    audit.record(action, target=obj, tenant_id=None)
    return obj


# --- Plans --------------------------------------------------------------------------------------

PLAN_FIELDS = (
    "name",
    "price_monthly",
    "max_retailers",
    "max_staff",
    "max_products",
    "features",
    "is_default",
    "is_active",
)


@transaction.atomic
def create_plan(data: dict[str, Any], *, by: User) -> Plan:
    plan = Plan(**{k: v for k, v in data.items() if k in (*PLAN_FIELDS, "code")})
    if plan.is_default:
        Plan.objects.filter(is_default=True).update(is_default=False)
    _check_plan_features(plan.features)
    return _create(plan, "plan.created")  # type: ignore[no-any-return]


@transaction.atomic
def update_plan(plan_id: Any, changes: dict[str, Any], *, by: User) -> Plan:
    plan: Plan = _get(Plan, pk=plan_id)
    if changes.get("is_default") is False and plan.is_default:
        raise InvalidFields({"is_default": [gettext("Make another plan the default instead.")]})
    if changes.get("is_default"):
        Plan.objects.filter(is_default=True).exclude(pk=plan.pk).update(is_default=False)
    if "features" in changes:
        _check_plan_features(changes["features"])
    _save_changed(plan, changes, PLAN_FIELDS, "plan.updated")
    return plan


def _check_plan_features(codes: Any) -> None:
    known = set(FeatureFlag.objects.values_list("code", flat=True))
    if not isinstance(codes, list) or not set(codes) <= known:
        raise InvalidFields({"features": [gettext("Use feature codes from the flag catalogue.")]})


# --- Feature flag catalogue ---------------------------------------------------------------------

FLAG_FIELDS = ("name", "description", "default_enabled", "tenant_toggleable")


@transaction.atomic
def update_feature_flag(code: str, changes: dict[str, Any], *, by: User) -> FeatureFlag:
    flag: FeatureFlag = _get(FeatureFlag, code=code)
    diff = _save_changed(flag, changes, FLAG_FIELDS, "feature_flag.updated")
    if "default_enabled" in diff:
        transaction.on_commit(invalidate_all_features)
    return flag


# --- GST rate master (ADR-008: activate/deactivate, never delete) -------------------------------


@transaction.atomic
def create_tax_rate(*, rate: Decimal, label: str, notes: str = "", by: User) -> TaxRate:
    if TaxRate.objects.filter(rate=rate).exists():
        raise InvalidFields({"rate": [gettext("This rate already exists.")]})
    return _create(TaxRate(rate=rate, label=label, notes=notes), "tax_rate.created")  # type: ignore[no-any-return]


@transaction.atomic
def update_tax_rate(tax_rate_id: Any, changes: dict[str, Any], *, by: User) -> TaxRate:
    """The rate itself is immutable (documents refer to it); label, notes and active can change."""
    tax_rate: TaxRate = _get(TaxRate, pk=tax_rate_id)
    _save_changed(tax_rate, changes, ("label", "notes", "is_active"), "tax_rate.updated")
    return tax_rate


# --- Cess types ---------------------------------------------------------------------------------


@transaction.atomic
def create_cess_type(data: dict[str, Any], *, by: User) -> CessType:
    return _create(CessType(**data), "cess_type.created")  # type: ignore[no-any-return]


@transaction.atomic
def update_cess_type(cess_id: Any, changes: dict[str, Any], *, by: User) -> CessType:
    cess: CessType = _get(CessType, pk=cess_id)
    _save_changed(cess, changes, ("name", "calc_method", "is_active"), "cess_type.updated")
    return cess


# --- HSN rate hints (suggestions only; never used to compute tax) -------------------------------


def _hint_rate(value: Any) -> Decimal:
    try:
        rate = Decimal(str(value).strip().rstrip("%"))
    except InvalidOperation as exc:
        raise ValueError("not a number") from exc
    if not TaxRate.objects.filter(rate=rate).exists():
        raise ValueError("not in the GST rate master")
    return rate


@transaction.atomic
def create_hsn_hint(data: dict[str, Any], *, by: User) -> HsnRateHint:
    try:
        data = {**data, "gst_rate": _hint_rate(data.get("gst_rate"))}
    except ValueError as exc:
        raise InvalidFields({"gst_rate": [gettext("Rate is %(exc)s.") % {"exc": exc}]}) from exc
    if HsnRateHint.objects.filter(
        hsn_prefix=data["hsn_prefix"], effective_from=data["effective_from"]
    ).exists():
        raise InvalidFields(
            {"hsn_prefix": [gettext("A hint for this prefix and date already exists.")]}
        )
    return _create(HsnRateHint(**data), "hsn_hint.created")  # type: ignore[no-any-return]


@transaction.atomic
def update_hsn_hint(hint_id: Any, changes: dict[str, Any], *, by: User) -> HsnRateHint:
    hint: HsnRateHint = _get(HsnRateHint, pk=hint_id)
    if "gst_rate" in changes:
        try:
            changes = {**changes, "gst_rate": _hint_rate(changes["gst_rate"])}
        except ValueError as exc:
            raise InvalidFields({"gst_rate": [gettext("Rate is %(exc)s.") % {"exc": exc}]}) from exc
    _save_changed(hint, changes, ("gst_rate", "description"), "hsn_hint.updated")
    return hint


@transaction.atomic
def delete_hsn_hint(hint_id: Any, *, by: User) -> None:
    hint: HsnRateHint = _get(HsnRateHint, pk=hint_id)
    audit.record(
        "hsn_hint.deleted",
        target=hint,
        tenant_id=None,
        metadata={"hsn_prefix": hint.hsn_prefix, "gst_rate": hint.gst_rate},
    )
    hint.delete()


@transaction.atomic
def import_hsn_hints(content: bytes, *, by: User) -> dict[str, int]:
    """CSV with columns hsn_prefix, gst_rate, effective_from (YYYY-MM-DD), description.

    All rows are validated first; nothing is saved if any row is wrong (the error lists the rows).
    Existing (prefix, date) pairs are updated.
    """
    if len(content) > HSN_IMPORT_MAX_BYTES:
        raise InvalidFields({"file": [gettext("The file is larger than 1 MB.")]})
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidFields({"file": [gettext("Save the file as UTF-8 CSV.")]}) from exc
    reader = csv.DictReader(io.StringIO(text))
    required = {"hsn_prefix", "gst_rate", "effective_from"}
    if not required <= set(reader.fieldnames or []):
        raise InvalidFields(
            {
                "file": [
                    gettext("Columns needed: hsn_prefix, gst_rate, effective_from, description.")
                ]
            }
        )
    rows: list[tuple[str, Decimal, date, str]] = []
    errors: list[str] = []
    for line, row in enumerate(reader, start=2):
        if len(rows) >= HSN_IMPORT_MAX_ROWS:
            errors.append(
                gettext("Row %(line)s: more than %(hsn_import_max_rows)s rows.")
                % {"line": line, "hsn_import_max_rows": HSN_IMPORT_MAX_ROWS}
            )
            break
        try:
            prefix = (row.get("hsn_prefix") or "").strip()
            validate_hsn_prefix(prefix)
            rate = _hint_rate(row.get("gst_rate"))
            effective = date.fromisoformat((row.get("effective_from") or "").strip())
            rows.append((prefix, rate, effective, (row.get("description") or "").strip()[:255]))
        except (DjangoValidationError, ValueError) as exc:
            message = exc.messages[0] if isinstance(exc, DjangoValidationError) else str(exc)
            errors.append(gettext("Row %(line)s: %(message)s") % {"line": line, "message": message})
    if errors:
        raise InvalidFields({"file": errors[:50]})
    created = updated = 0
    for prefix, rate, effective, description in rows:
        _, was_created = HsnRateHint.objects.update_or_create(
            hsn_prefix=prefix,
            effective_from=effective,
            defaults={"gst_rate": rate, "description": description},
        )
        created += int(was_created)
        updated += int(not was_created)
    audit.record(
        "hsn_hint.imported",
        target_type="hsn_hint",
        tenant_id=None,
        metadata={"created": created, "updated": updated},
    )
    return {"created": created, "updated": updated}
