"""ADR-042: cost prices, receipt costs and stock value reach only staff with ``costs.view``.

Every GET route of the tenant API is called as a Sales and a Warehouse user (neither has
costs.view), with real ids filled in. No response (JSON, Excel or CSV) may contain any cost figure
that exists in the database, and every cost-named field must be null."""

import io
import json
import re
import uuid
import zipfile
from decimal import Decimal as D

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.catalog.models import Product
from apps.dataio.services import KINDS
from apps.inventory import adjustments, receipts
from apps.inventory.models import StockAdjustment, StockInward, StockInwardLine, StockMovement
from apps.inventory.selectors import valuation
from apps.inventory.tests.helpers import make_product
from apps.pricing.models import PriceList
from apps.retailers.services import create_retailer
from common.tenancy import tenant_context
from common.testing.isolation import api_routes

pytestmark = pytest.mark.django_db
# Field names that only ever hold a cost. ("value" is used by settings too; movement and
# valuation values are caught by the figure search.)
COST_KEYS = {"cost_price", "unit_cost", "entered_cost", "line_cost", "total_cost"}


def _client(tenant, role):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {issue_tokens(make_staff_in(tenant, role), tenant.pk).access}"
    )
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


@pytest.fixture
def costed(tenant_a):
    """Distinctive costs everywhere: product cost prices, a costed receipt (movement values,
    weighted average), a receipt awaiting cost and an opening stock adjustment with a cost."""
    cache.clear()
    owner = make_staff_in(tenant_a, "OWNER")
    warehouse = make_staff_in(tenant_a, "WAREHOUSE")
    a = make_product(tenant_a, "COST-A", cost_price=D("4321.77"))
    b = make_product(tenant_a, "COST-B")
    with tenant_context(tenant_a.pk):
        receipts.create_and_post(
            receipts.ReceiptInput(
                lines=[receipts.LineInput(a.pk, D("3"), entered_cost=D("1234.5678"))],
                supplier_name="Costly Traders",
            ),
            by=owner,
        )
        pending = receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(b.pk, D("2"))]), by=warehouse
        )
        adjustments.create_adjustment(
            adjustments.AdjustmentInput(
                "OPENING_STOCK",
                "Opening",
                [adjustments.AdjustmentLineInput(b.pk, "ADD", D("5"), unit_cost=D("2468.1357"))],
            ),
            by=owner,
        )
        retailer = create_retailer(shop_name="Cost Shop", phone="9876500077", send_welcome=False)
        price_list = PriceList.objects.create(name="Gold")
        figures = _cost_figures()
        ids = {
            "product_id": a.pk,
            "inward_id": pending.pk,
            "adjustment_id": StockAdjustment.objects.get().pk,
            "warehouse_id": StockInward.objects.values_list("warehouse_id", flat=True)[0],
            "retailer_id": retailer.pk,
            "price_list_id": price_list.pk,
        }
    return figures, ids


def _cost_figures():
    """Every cost number in the database, as the API or a spreadsheet would write it."""
    values = set()
    values |= set(Product.objects.exclude(cost_price=None).values_list("cost_price", flat=True))
    for row in StockMovement.objects.values_list("unit_cost", "value"):
        values |= {v for v in row if v is not None}
    for row in StockInwardLine.objects.values_list("entered_cost", "unit_cost", "line_cost"):
        values |= {v for v in row if v is not None}
    values |= {v for v in StockInward.objects.values_list("total_cost", flat=True) if v}
    values.add(valuation().total_value)
    figures = set()
    for value in values:
        figures |= {f"{value}", f"{value.normalize():f}", f"{value:.2f}", f"{value:.4f}"}
    assert len(values) >= 6
    return {f for f in figures if len(f.replace(".", "").lstrip("0")) >= 5}  # distinctive only


def _paths(ids):
    kinds = [k.lower() for k in KINDS]
    for route, name in api_routes():
        if route.startswith("api/v1/platform/") or name in ("schema", "docs"):
            continue
        params = re.findall(r"<(\w+):(\w+)>", route)
        options = [route]
        for converter, param in params:
            expanded = []
            for path in options:
                token = f"<{converter}:{param}>"
                if param == "kind":
                    expanded += [path.replace(token, k) for k in kinds]
                elif converter == "uuid":
                    expanded.append(path.replace(token, str(ids.get(param, uuid.uuid4()))))
                else:
                    expanded.append(path.replace(token, "x"))
            options = expanded
        for path in options:
            yield "/" + path


def _text(response, *, check_keys=True):
    content_type = response.get("Content-Type", "")
    body = b"".join(response.streaming_content) if response.streaming else response.content
    if body[:2] == b"PK":  # xlsx
        with zipfile.ZipFile(io.BytesIO(body)) as book:
            return " ".join(book.read(n).decode("utf-8", "replace") for n in book.namelist())
    if "json" in content_type and check_keys:
        _assert_cost_keys_null(json.loads(body or b"null"))
    return body.decode("utf-8", "replace")


def _assert_cost_keys_null(data, where="$"):
    if isinstance(data, dict):
        for key, item in data.items():
            if key in COST_KEYS:
                assert item is None, f"{where}.{key} = {item!r}"
            _assert_cost_keys_null(item, f"{where}.{key}")
    elif isinstance(data, list):
        for index, item in enumerate(data):
            _assert_cost_keys_null(item, f"{where}[{index}]")


@pytest.mark.parametrize("role", ["SALES", "WAREHOUSE"])
def test_staff_without_costs_view_never_receive_a_cost(tenant_a, costed, role):
    figures, ids = costed
    client = _client(tenant_a, role)
    seen = {"ok": 0}
    leaks = []
    for path in _paths(ids):
        response = client.get(path)
        if response.status_code != 200:
            continue
        seen["ok"] += 1
        try:
            text = _text(response)
        except AssertionError as exc:
            leaks.append(f"{path}: {exc}")
            continue
        found = sorted(f for f in figures if re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", text))
        if found:
            leaks.append(f"{path}: {found}")
    assert leaks == []
    assert seen["ok"] > 20  # the walk really reached the product, stock and export routes


def test_the_same_walk_finds_costs_for_accounts(tenant_a, costed):
    """Control: with costs.view, the costs are there, so the test above can't pass by accident."""
    figures, ids = costed
    client = _client(tenant_a, "ACCOUNTS")
    texts = [
        _text(client.get(path), check_keys=False)
        for path in (
            f"/api/v1/products/{ids['product_id']}/",
            "/api/v1/stock/movements/",
            f"/api/v1/stock/inwards/{ids['inward_id']}/",
        )
    ]
    assert any(f in t for f in figures for t in texts)
