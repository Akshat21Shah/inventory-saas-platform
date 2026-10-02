"""The assistant's evaluation set (ADR-059 item 7): realistic questions, the tool and arguments
each should use, and the facts its answer must mention, worked out by running the same report
directly. Run in CI with the scripted mock (``test_assistant_eval``) and against a real model with
``manage.py ai_eval``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from apps.accounts.models import User
from apps.ai.adapters.mock_chat import quantity, rupees
from apps.ai.assistant import tools as toolbox
from apps.ai.models import AssistantQuestion


@dataclass(frozen=True)
class Case:
    question: str
    tool: str | None  # None: no tool fits, the answer says what it can do
    args: dict[str, Any] = field(default_factory=dict)  # must be among the call's arguments


def _top(rows: list[dict[str, Any]], key: str = "total") -> list[str]:
    return [str(rows[0]["name"]), rupees(rows[0][key])] if rows else []


FACTS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "sales_summary": lambda f: (
        [rupees((f["totals"] or {}).get("total"))]
        if Decimal(str((f["totals"] or {}).get("total") or 0))
        else ["No sales"]
    ),
    "top_products": lambda f: _top(f["rows"]) or ["No sales"],
    "sales_by_category": lambda f: _top(f["rows"]) or ["No sales"],
    "top_shops": lambda f: _top(f["rows"]) or ["No sales"],
    "sales_by_salesperson": lambda f: _top(f["rows"]) or ["No sales"],
    "shops_not_ordering": lambda f: [str(r["name"]) for r in f["rows"][:3]] or ["Every shop"],
    "low_stock": lambda f: [str(f["rows"][0]["name"])] if f["rows"] else ["Nothing is below"],
    "product_stock": lambda f: (
        [str(f["rows"][0]["name"]), quantity(f["rows"][0]["available"])]
        if f["rows"]
        else ["couldn't find"]
    ),
    "dues": lambda f: (
        [
            next(str(r["name"]) for r in f["rows"] if Decimal(str(r["net"] or 0)) > 0),
            rupees((f["totals"] or {}).get("net")),
        ]
        if any(Decimal(str(r["net"] or 0)) > 0 for r in f["rows"])
        else ["owes anything"]
    ),
    "collections": lambda f: (
        [rupees((f["totals"] or {}).get("amount"))] if f["rows"] else ["No payments"]
    ),
    "backorders": lambda f: [str(f["rows"][0]["name"])] if f["rows"] else ["No shop is waiting"],
}

CASES: tuple[Case, ...] = (
    Case("Which shops haven't ordered in 30 days?", "shops_not_ordering", {"days": 30}),
    Case("Show me shops that have not ordered for 60 days", "shops_not_ordering", {"days": 60}),
    Case(
        "What are our top 5 products this month?",
        "top_products",
        {"period": "this_month", "limit": 5},
    ),
    Case("Best selling products last month", "top_products", {"period": "last_month"}),
    Case("How much did we sell today?", "sales_summary", {"period": "today"}),
    Case(
        "What are our sales this financial year?",
        "sales_summary",
        {"period": "this_financial_year"},
    ),
    Case(
        "Who are our top 10 shops this quarter?",
        "top_shops",
        {"period": "this_quarter", "limit": 10},
    ),
    Case("Sales by category in the last 30 days", "sales_by_category", {"period": "last_30_days"}),
    Case(
        "How are the salesmen doing this month?", "sales_by_salesperson", {"period": "this_month"}
    ),
    Case("Which products are running low?", "low_stock"),
    Case("How much stock of {product} do we have?", "product_stock"),
    Case("Who owes us the most money?", "dues"),
    Case("Which shops have overdue payments?", "dues", {"overdue_only": True}),
    Case("How much did we collect this week?", "collections", {"period": "this_week"}),
    Case("What are shops waiting for on backorder?", "backorders"),
    Case("What will the weather be tomorrow?", None),
)


def _mentions(answer: str, fact: str) -> bool:
    """The fact appears in the answer; amounts also match without paise or digit grouping."""
    if fact.lower() in answer.lower():
        return True
    money = re.fullmatch(r"-?₹([\d,]+)\.(\d\d)", fact)
    if money:
        digits = money.group(1).replace(",", "")
        plain = answer.replace(",", "")
        return re.search(rf"(?<!\d){digits}(?:\.{money.group(2)})?(?!\d)", plain) is not None
    return False


@dataclass
class Outcome:
    case: Case
    question: str
    answer: str = ""
    problems: list[str] = field(default_factory=list)
    model: str = ""  # what answered it
    units_in: int = 0
    units_out: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.problems


def check(case: Case, asked: AssistantQuestion, user: User) -> list[str]:
    """What is wrong with how ``asked`` was answered (empty: right)."""
    problems: list[str] = []
    if asked.status != AssistantQuestion.Status.ANSWERED:
        return [f"not answered: {asked.status} {asked.error}"]
    calls = [c for c in asked.tools if c.get("ok")]
    if case.tool is None:
        if calls:
            problems.append(f"called {calls[0]['name']} for a question no tool answers")
        return problems
    call = next((c for c in calls if c["name"] == case.tool), None)
    if call is None:
        return [f"didn't call {case.tool} (called {[c['name'] for c in asked.tools]})"]
    for key, value in case.args.items():
        if call["args"].get(key) != value:
            problems.append(f"{key}={call['args'].get(key)!r}, expected {value!r}")
    # The facts come from the report run directly with the same arguments, not from the call.
    direct = toolbox.run(user, case.tool, call["args"]).as_json()
    for fact in FACTS[case.tool](direct):
        if not _mentions(asked.answer, fact):
            problems.append(f"the answer doesn't mention {fact!r}")
    return problems


def run_case(case: Case, user: User, *, product: str = "", model: str | None = None) -> Outcome:
    """Ask ``case`` as ``user`` (in the active distributor), with ``model`` instead of the
    platform setting when given, and check the answer."""
    from apps.ai.assistant import service

    question = case.question.format(product=product)
    asked = AssistantQuestion.objects.create(user=user, question=question)
    asked = service.answer(asked.pk, model=model)
    return Outcome(
        case,
        question,
        asked.answer,
        check(case, asked, user),
        model=asked.model,
        units_in=asked.units_in,
        units_out=asked.units_out,
        seconds=asked.duration_ms / 1000,
    )
