import time
from decimal import Decimal

import pytest

from common.hosts import HostKind, classify_host
from common.ids import uuid7
from common.money import quantize_money, quantize_qty, to_decimal


def test_uuid7_version_variant_and_time_order():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.version == 7
    assert first.variant == "specified in RFC 4122"
    assert first < second  # time-ordered across milliseconds


def test_uuid7_unique():
    assert len({uuid7() for _ in range(10_000)}) == 10_000


@pytest.mark.parametrize("bad", [1.1, True])
def test_to_decimal_refuses_float_and_bool(bad):
    with pytest.raises(TypeError):
        to_decimal(bad)


def test_quantize_helpers_half_up():
    assert quantize_money("111.105") == Decimal("111.11")
    assert quantize_money(Decimal("0.005")) == Decimal("0.01")
    assert quantize_qty("2.7505") == Decimal("2.751")


@pytest.mark.parametrize(
    ("host", "kind", "slug"),
    [
        ("localhost:3000", HostKind.GENERIC, None),
        ("admin.localhost", HostKind.ADMIN, None),
        ("sharma.localhost:8000", HostKind.TENANT, "sharma"),
        ("Sharma.LOCALHOST", HostKind.TENANT, "sharma"),
        ("www.localhost", HostKind.GENERIC, None),
        ("api.localhost", HostKind.UNKNOWN, None),
        ("a.b.localhost", HostKind.UNKNOWN, None),
        ("evil.com", HostKind.UNKNOWN, None),
        ("-bad.localhost", HostKind.UNKNOWN, None),
    ],
)
def test_classify_host(host, kind, slug):
    ctx = classify_host(host, "localhost")
    assert ctx.kind == kind
    assert ctx.tenant_slug == slug
