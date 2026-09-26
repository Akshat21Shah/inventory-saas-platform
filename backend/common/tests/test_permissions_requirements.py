"""Nested permission requirements (``AnyOf`` / ``AllOf``) used by endpoints."""

from common.permissions import AllOf, AnyOf, codes_of, satisfies

VALUATION = AllOf(("costs.view", AnyOf(("reports.stock", "reports.financial"))))


def has(*codes: str):
    return lambda code: code in codes


def test_nested_requirements():
    assert satisfies(has("costs.view", "reports.financial"), VALUATION)
    assert satisfies(has("costs.view", "reports.stock"), VALUATION)
    assert not satisfies(has("costs.view"), VALUATION)
    assert not satisfies(has("reports.stock", "reports.financial"), VALUATION)
    assert satisfies(has("a"), "a") and not satisfies(has("b"), "a")


def test_codes_of_flattens():
    assert codes_of(VALUATION) == ("costs.view", "reports.stock", "reports.financial")
