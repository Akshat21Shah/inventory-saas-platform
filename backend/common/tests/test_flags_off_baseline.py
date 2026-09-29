"""With the Phase 7 flags off, the app behaves exactly as before Phase 7 (ADR-049 item 1).

A full flow runs with `einvoice`, `ewaybill` and `payments` off: an inter-state B2B sale worth
more than the e-way bill threshold, a local B2C sale, a return, a bank transfer, a bounced cheque,
cash and a refund. What it leaves behind is compared with a snapshot captured before any Phase 7
code (``baseline/``):

- every row of every table holding the tenant's data (tables added later must stay empty);
- the printed invoices, credit note and receipts (the HTML the PDFs are made from);
- the staff and shop API responses a person sees for them;
- every WhatsApp, SMS and email the mocks sent.

Ids, timestamps, dates and the financial year are normalised, so the snapshot doesn't depend on
when it runs. A field added since the snapshot is allowed only when it is listed in
``ALLOWED_NEW`` with the value it must have while the flags are off.

The snapshot was captured once, before Phase 7 (``BASELINE_UPDATE=1 pytest this file``). Never
regenerate it to make a Phase 7 change pass: that is what the test exists to catch.
"""

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from django.apps import apps
from django.core import mail
from django.db import models
from django.template.loader import render_to_string

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.models import User
from apps.accounts.tests.factories import make_membership
from apps.billing import credit_notes, documents
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import CreditNote, Invoice
from apps.billing.tax import financial_year, fy_short
from apps.inventory.tests.helpers import make_product
from apps.notifications import consent, quiet
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from apps.orders import fulfilment, transitions
from apps.orders.fulfilment import Transport
from apps.orders.models import Fulfilment
from apps.orders.tests.helpers import add_stock, client_for, place, shop_user
from apps.payments import services as payments
from apps.payments.models import Payment, Refund
from apps.payments.services import PaymentInput, RefundInput
from apps.platform import selectors
from apps.platform.models import FeatureFlag, Tenant, TenantFeature
from apps.platform.tests.factories import TenantFactory, make_gstin
from apps.retailers.services import AddressInput, create_retailer
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db

BASELINE = Path(__file__).parent / "baseline"
PHASE_7_FLAGS = ("einvoice", "ewaybill", "payments")

# Fields added after the snapshot, with the value each must have while the flags are off.
# Keys: "db.<app.Model>.<field>" or "api.<name>.<dotted path>" (list positions left out).
ALLOWED_NEW: dict[str, Any] = {}

# Random by design: stored as "<random>".
VOLATILE = {
    "accounts.User.password",
    "notifications.DocumentLink.token_hash",
    "notifications.Notification.provider_message_id",
    "notifications.DeliveryAttempt.response",
    "notifications.DeliveryAttempt.duration_ms",
}

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
TEXT_DATE_RE = re.compile(rf"\b(\d{{1,2}}) ({MONTHS}) (\d{{4}})\b")
NUM_DATE_RE = re.compile(r"\b(\d{2})([-/])(\d{2})\2(\d{4})\b")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?( ?[AaPp][Mm])?\b")
TOKEN_RE = re.compile(r"/public/documents/[A-Za-z0-9_-]+/")
SIGNED_RE = re.compile(r"\?[^\s\"']*X-Amz-[^\s\"']*")


class Normaliser:
    """Replaces what changes from run to run with stable labels."""

    def __init__(self, today: date) -> None:
        self.today = today
        self.labels: dict[str, str] = {}
        fy = financial_year(today)
        self.fy = [(fy, "<FY>"), (fy_short(fy), "<FY>")]

    def label(self, value: Any, name: str) -> None:
        self.labels[str(value)] = name

    def _day(self, day: date) -> str:
        return f"D{(day - self.today).days:+d}"

    def text(self, value: str) -> str:
        if TIMESTAMP_RE.match(value):
            return "<ts>"
        value = UUID_RE.sub(lambda m: self.labels.get(m.group(0), "<uuid>"), value)
        value = TOKEN_RE.sub("/public/documents/<token>/", value)
        value = SIGNED_RE.sub("?<signed>", value)
        value = ISO_DATE_RE.sub(lambda m: self._day(date(*map(int, m.groups()))), value)
        value = TEXT_DATE_RE.sub(
            lambda m: self._day(datetime.strptime(m.group(0), "%d %b %Y").date()), value
        )
        value = NUM_DATE_RE.sub(
            lambda m: self._day(date(int(m.group(4)), int(m.group(3)), int(m.group(1)))), value
        )
        value = TIME_RE.sub("<time>", value)
        for real, stable in self.fy:
            value = value.replace(real, stable)
        return value

    def value(self, value: Any) -> Any:
        if value is None or isinstance(value, bool | int):
            return value
        if isinstance(value, datetime):
            return "<ts>"
        if isinstance(value, date):
            return self._day(value)
        if isinstance(value, UUID):
            return self.labels.get(str(value), "<uuid>")
        if isinstance(value, D):
            return str(value)
        if isinstance(value, dict):
            return {str(k): self.value(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.value(v) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return self.text(str(value))

    def html(self, html: str) -> str:
        return "\n".join(line.strip() for line in self.text(html).splitlines() if line.strip())


# --- The flow ---------------------------------------------------------------------------------


def _flow() -> dict[str, Any]:
    tenant = TenantFactory.create(
        name="Baseline Traders",
        legal_name="Baseline Traders Private Limited",
        slug="baseline",
        gstin=make_gstin(4242),
        email="owner@baseline.example.com",
    )
    owner = User.objects.create_user(
        "owner@baseline.example.com", "a-strong-password", user_type=User.UserType.STAFF
    )
    make_membership(owner, tenant, "OWNER")
    with tenant_context(tenant.pk):
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(tenant.pk)
    snacks = make_product(tenant, "SNK-1", name="Masala Biscuits", base_price=D("100"))
    laptop = make_product(tenant, "LAP-1", name="Laptop", hsn_code="8471", base_price=D("30000"))
    add_stock(tenant, snacks, "100")
    add_stock(tenant, laptop, "10")

    with tenant_context(tenant.pk):
        b2b = create_retailer(
            shop_name="Kaveri Traders",
            phone="9876500061",
            email="kaveri@example.com",
            gstin=make_gstin(4343, "29"),
            billing=AddressInput("4 MG Road", "Bengaluru", "560001", "29"),
        )
        b2c = create_retailer(
            shop_name="Ganesh Kirana",
            phone="9876500062",
            email="ganesh@example.com",
            billing=AddressInput("12 Market Road", "Pune", "411001", "27"),
        )
        consent.set_whatsapp_consent(
            b2b.pk, True, source=consent.Source.SHOP_APP, by=shop_user(b2b)
        )

    def ship(order: Any, transport: Transport) -> Invoice:
        with tenant_context(tenant.pk):
            transitions.accept_order(order.pk, by=owner)
            shipment = Fulfilment.objects.get(order=order)
            fulfilment.pack(shipment.pk, {}, by=owner)
            fulfilment.dispatch(shipment.pk, transport, by=owner)
            fulfilment.deliver(shipment.pk, by=owner)
            invoice: Invoice = Invoice.objects.get(fulfilment=shipment)
            return invoice

    big = ship(
        place(tenant, b2b, (laptop, "2"), (snacks, "5")),
        Transport("MH12AB1234", "Speedy Roadways", "LR-778"),
    )
    small = ship(place(tenant, b2c, (snacks, "3")), Transport())
    with tenant_context(tenant.pk):
        line = big.lines.get(product=snacks)
        note = credit_notes.issue_return(
            big.pk, [ReturnLine(line.pk, D("1"))], reason="DAMAGED", note="", by=owner
        )
        transfer = payments.record_payment(
            PaymentInput(b2b.pk, D("50000.00"), "BANK_TRANSFER", today_ist(), reference_no="UTR1"),
            by=owner,
        )
        cheque = payments.record_payment(
            PaymentInput(b2b.pk, D("5000.00"), "CHEQUE", today_ist(), cheque_number="004512"),
            by=owner,
        )
        payments.bounce_cheque(cheque.pk, reason="Insufficient funds", by=owner)
        cash = payments.record_payment(
            PaymentInput(b2c.pk, small.grand_total + D("40.00"), "CASH", today_ist()), by=owner
        )
        refund = payments.record_refund(
            RefundInput(b2c.pk, D("40.00"), "UPI", today_ist()), by=owner
        )
    return {
        "tenant": tenant,
        "owner": owner,
        "b2b": b2b,
        "b2c": b2c,
        "invoices": {"big": big, "small": small},
        "note": note,
        "payments": {"transfer": transfer, "cheque": cheque, "cash": cash},
        "refund": refund,
    }


# --- What the flow leaves behind --------------------------------------------------------------


def _tenant_models() -> list[type[models.Model]]:
    found = []
    for model in apps.get_models():
        field = next((f for f in model._meta.concrete_fields if f.name == "tenant"), None)
        if field is not None and field.related_model is Tenant:
            found.append(model)
    return sorted(found, key=lambda m: m._meta.label)


def _row(model: type[models.Model], obj: models.Model) -> dict[str, Any]:
    row = {}
    for field in model._meta.concrete_fields:
        if field.name in ("id", "tenant"):
            continue
        volatile = f"{model._meta.label}.{field.name}" in VOLATILE
        row[field.attname] = "<random>" if volatile else field.value_from_object(obj)
    return row


def _database(tenant: Tenant, norm: Normaliser) -> dict[str, list[Any]]:
    raw: dict[str, list[tuple[Any, dict[str, Any], Any]]] = {}
    with tenant_context(tenant.pk):
        for model in _tenant_models():
            objs = model._base_manager.filter(tenant_id=tenant.pk)
            raw[model._meta.label] = [(obj.pk, _row(model, obj), obj) for obj in objs]
    # Rows are labelled by rank of their content, not by id: ids differ on every run. Each pass
    # ranks with the labels of the rows they point to from the pass before, until nothing moves;
    # rows still alike are ranked by creation time.
    fixed = dict(norm.labels)
    for _ in range(6):
        before = dict(norm.labels)
        for label, rows in raw.items():
            ranked = sorted(
                rows,
                key=lambda r: (
                    json.dumps(norm.value(r[1]), sort_keys=True),
                    getattr(r[2], "created_at", None) or datetime.min,
                ),
            )
            raw[label] = ranked
            for i, (pk, _, _) in enumerate(ranked, 1):
                if str(pk) not in fixed:
                    norm.labels[str(pk)] = f"{label.split('.')[1]}#{i}"
        if norm.labels == before:
            break
    return {label: [norm.value(row) for _, row, _ in rows] for label, rows in raw.items()}


def _documents(flow: dict[str, Any], norm: Normaliser) -> dict[str, str]:
    tenant = flow["tenant"]
    out = {}
    with tenant_context(tenant.pk):
        for name, invoice in flow["invoices"].items():
            invoice = Invoice.objects.select_related("order", "place_of_supply").get(pk=invoice.pk)
            context = documents.invoice_context(invoice, documents.COPIES)
            out[f"invoice-{name}"] = render_to_string("billing/invoice.html", context)
        note = CreditNote.objects.select_related("invoice", "place_of_supply").get(
            pk=flow["note"].pk
        )
        out["credit-note"] = render_to_string(
            "billing/credit_note.html", documents.credit_note_context(note)
        )
        for name, payment in flow["payments"].items():
            payment = Payment.objects.get(pk=payment.pk)
            out[f"receipt-{name}"] = render_to_string(
                "billing/receipt.html", documents.receipt_context(payment)
            )
        refund = Refund.objects.get(pk=flow["refund"].pk)
        out["refund"] = render_to_string("billing/refund.html", documents.refund_context(refund))
    return {name: norm.html(html) for name, html in out.items()}


def _api(flow: dict[str, Any], norm: Normaliser) -> dict[str, Any]:
    tenant, big, note = flow["tenant"], flow["invoices"]["big"], flow["note"]
    staff = client_for(tenant, flow["owner"])
    shop = client_for(tenant, shop_user(flow["b2b"]))
    transfer = flow["payments"]["transfer"]
    calls = {
        "invoices": (staff, "/api/v1/invoices/"),
        "invoice": (staff, f"/api/v1/invoices/{big.pk}/"),
        "credit-note": (staff, f"/api/v1/credit-notes/{note.pk}/"),
        "payments": (staff, "/api/v1/payments/"),
        "payment": (staff, f"/api/v1/payments/{transfer.pk}/"),
        "order": (staff, f"/api/v1/orders/{big.order_id}/"),
        "fulfilment": (staff, f"/api/v1/fulfilments/{big.fulfilment_id}/"),
        "retailer": (staff, f"/api/v1/retailers/{flow['b2b'].pk}/"),
        "retailer-ledger": (staff, f"/api/v1/retailers/{flow['b2b'].pk}/ledger/"),
        "receivables": (staff, "/api/v1/receivables/"),
        "settings-registry": (staff, "/api/v1/settings/registry/"),
        "settings-features": (staff, "/api/v1/settings/features/"),
        "notification-rules": (staff, "/api/v1/notification-rules/"),
        "shop-home": (shop, "/api/v1/shop/home/"),
        "shop-account": (shop, "/api/v1/shop/account/"),
        "shop-invoices": (shop, "/api/v1/shop/invoices/"),
        "shop-invoice": (shop, f"/api/v1/shop/invoices/{big.pk}/"),
        "shop-payments": (shop, "/api/v1/shop/payments/"),
        "shop-ledger": (shop, "/api/v1/shop/ledger/"),
        "shop-order": (shop, f"/api/v1/shop/orders/{big.order_id}/"),
    }
    out = {}
    for name, (client, url) in calls.items():
        response = client.get(url)
        assert response.status_code == 200, (name, response.status_code, response.content[:300])
        out[name] = norm.value(response.json())
    return out


def _messages(norm: Normaliser) -> dict[str, Any]:
    whatsapp = [
        {
            "to": m.message.to,
            "template": m.message.template,
            "params": list(m.message.parameters),
            "text": m.message.text,
        }
        for m in MockWhatsAppClient.outbox
    ]
    sms = [{"to": m.phone, "text": m.text, "template": m.template} for m in MockSmsSender.outbox]
    email = [{"to": m.to, "subject": m.subject, "body": m.body} for m in mail.outbox]
    return {
        "whatsapp": sorted(norm.value(whatsapp), key=lambda m: json.dumps(m, sort_keys=True)),
        "sms": sorted(norm.value(sms), key=lambda m: json.dumps(m, sort_keys=True)),
        "email": sorted(norm.value(email), key=lambda m: json.dumps(m, sort_keys=True)),
    }


# --- Comparison -------------------------------------------------------------------------------


def _pattern(path: str) -> str:
    return re.sub(r"\[\d+\]", "", path)


def _compare(before: Any, now: Any, path: str, diffs: list[str]) -> None:
    if isinstance(before, dict) and isinstance(now, dict):
        for key in before:
            if key not in now:
                diffs.append(f"{path}.{key}: missing")
            else:
                _compare(before[key], now[key], f"{path}.{key}", diffs)
        for key in now.keys() - before.keys():
            where = _pattern(f"{path}.{key}")
            if where not in ALLOWED_NEW:
                diffs.append(f"{where}: new, not in ALLOWED_NEW ({now[key]!r})")
            elif now[key] != ALLOWED_NEW[where]:
                diffs.append(f"{where}: {now[key]!r} while the flags are off")
    elif isinstance(before, list) and isinstance(now, list):
        if len(before) != len(now):
            diffs.append(f"{path}: {len(before)} items before, {len(now)} now")
        for i, (b, n) in enumerate(zip(before, now, strict=False)):
            _compare(b, n, f"{path}[{i}]", diffs)
    elif before != now:
        diffs.append(f"{path}: {before!r} -> {now!r}")


def _compare_database(before: dict[str, Any], now: dict[str, Any], diffs: list[str]) -> None:
    for label, rows in now.items():
        if label not in before:
            if rows:
                diffs.append(f"db.{label}: a new table has {len(rows)} rows with the flags off")
            continue
        _compare(before[label], rows, f"db.{label}", diffs)
    for label in before.keys() - now.keys():
        diffs.append(f"db.{label}: table gone")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    MockWhatsAppClient.outbox.clear()
    MockSmsSender.outbox.clear()
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)


def test_the_app_behaves_as_before_phase_7_with_its_flags_off(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        flow = _flow()
    tenant = flow["tenant"]
    assert not any(
        selectors.is_feature_enabled(code, tenant.pk)
        for code in PHASE_7_FLAGS
        if FeatureFlag.objects.filter(code=code).exists()
    )

    norm = Normaliser(today_ist())
    norm.label(tenant.pk, "tenant")
    for user in User.objects.filter(email__endswith="@baseline.example.com") | User.objects.filter(
        tenant=tenant
    ):
        norm.label(user.pk, f"user:{user.email or user.phone}")
    current = {
        "db": _database(tenant, norm),
        "api": _api(flow, norm),
        "messages": _messages(norm),
    }
    docs = _documents(flow, norm)

    if os.environ.get("BASELINE_UPDATE") == "1":
        BASELINE.mkdir(exist_ok=True)
        (BASELINE / "state.json").write_text(
            json.dumps(current, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        )
        for name, html in docs.items():
            (BASELINE / f"{name}.html").write_text(html + "\n")
        pytest.skip("baseline written")

    before = json.loads((BASELINE / "state.json").read_text())
    diffs: list[str] = []
    _compare_database(before["db"], current["db"], diffs)
    _compare(before["api"], current["api"], "api", diffs)
    _compare(before["messages"], current["messages"], "messages", diffs)
    for name, html in docs.items():
        if (BASELINE / f"{name}.html").read_text() != html + "\n":
            diffs.append(f"document {name}: printed differently")
    assert not diffs, "With the Phase 7 flags off:\n" + "\n".join(diffs[:60])
