"""The scripted mock assistant (ADR-059 item 4): local, deterministic and free, for dev, tests,
CI and the evaluation set. It picks one tool from the question's words (and a period, a number of
rows or days, or a product), then writes a short answer from the tool's figures with a template.
It knows English only; a real model understands far more.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from apps.ai.adapters.chat import ChatTurn, Message, ToolCall, ToolSpec

MODEL = "mock-scripted-1"

# The first match wins, so the more specific phrases come first.
ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (tool, re.compile(pattern, re.IGNORECASE))
    for tool, pattern in (
        (
            "shops_not_ordering",
            r"(haven'?t|have not|not|stopped|didn'?t)\s+order|win back|dormant|inactive"
            r"|no orders? from",
        ),
        ("backorders", r"backorder|waiting for|short supplied|pending supply"),
        ("low_stock", r"low (on )?stock|running (out|low)|reorder|out of stock|short of"),
        ("product_stock", r"(stock|how (many|much)) (of|for|do we have)|in stock|stock left"),
        ("dues", r"\bowe|dues?\b|outstanding|overdue|receivable|pending payment"),
        ("collections", r"collect|payments? (received|came|in)|received (payments?|money)"),
        ("sales_by_salesperson", r"salesm[ae]n|salesperson|sales (staff|team|people)"),
        ("sales_by_category", r"categor"),
        (
            "top_shops",
            r"(top|best|biggest|largest)\s+(\d+\s+)?(shops?|customers?|retailers?|buyers?)"
            r"|which shops? (bought|ordered|buy) (the )?most",
        ),
        (
            "top_products",
            r"(top|best|most)\s*(\d+\s+)?(selling|sold|products?|items?)|best.?sellers?|what sold",
        ),
        (
            "sales_summary",
            r"\bsales?\b|\bsold\b|\bsell\b|revenue|turnover|billed|business (this|last|today)",
        ),
    )
)
PERIODS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (period, re.compile(pattern, re.IGNORECASE))
    for period, pattern in (
        ("today", r"\btoday\b"),
        ("yesterday", r"\byesterday\b"),
        ("last_week", r"\blast week\b|\bprevious week\b"),
        ("this_week", r"\bthis week\b"),
        ("last_7_days", r"\b(last|past) (7|seven) days\b"),
        ("last_30_days", r"\b(last|past) (30|thirty) days\b"),
        ("last_90_days", r"\b(last|past) (90|ninety) days\b|\blast (3|three) months\b"),
        ("last_month", r"\blast month\b|\bprevious month\b"),
        ("this_month", r"\bthis month\b"),
        ("last_quarter", r"\blast quarter\b"),
        ("this_quarter", r"\bthis quarter\b"),
        ("last_financial_year", r"\blast (financial )?year\b"),
        ("this_financial_year", r"\bthis (financial )?year\b"),
    )
)
WORDS = {
    "today": "today",
    "yesterday": "yesterday",
    "this_week": "this week",
    "last_week": "last week",
    "last_7_days": "in the last 7 days",
    "this_month": "this month",
    "last_month": "last month",
    "last_30_days": "in the last 30 days",
    "last_90_days": "in the last 90 days",
    "this_quarter": "this quarter",
    "last_quarter": "last quarter",
    "this_financial_year": "this financial year",
    "last_financial_year": "last financial year",
}
_PRODUCT = re.compile(
    r"(?:stock of|stock for|how (?:many|much)(?: stock)?(?: of)?)\s+(?P<name>.+?)"
    r"(?:\s+(?:do we have|have we got|is left|are left|left|in stock|we have))?\s*\??$",
    re.IGNORECASE,
)


def rupees(value: Any) -> str:
    """'123456.5' → '₹1,23,456.50' (Indian grouping)."""
    number = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    sign = "-" if number < 0 else ""
    whole, _, paise = f"{abs(number):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹{','.join([*groups, tail]) if groups else tail}.{paise}"


def quantity(value: Any) -> str:
    return f"{Decimal(str(value or 0)).normalize():f}"


def _period(question: str) -> str | None:
    for period, pattern in PERIODS:
        if pattern.search(question):
            return period
    return None


def _number(pattern: str, question: str) -> int | None:
    found = re.search(pattern, question, re.IGNORECASE)
    return int(found.group(1)) if found else None


def plan(question: str, offered: set[str]) -> ToolCall | str:
    """The tool call for ``question``, or a reply when no offered tool fits."""
    for tool, pattern in ROUTES:
        if not pattern.search(question):
            continue
        if tool not in offered:
            return "You don't have access to those figures. Ask the owner if you need them."
        args: dict[str, Any] = {}
        period = _period(question)
        if period and tool in (
            "sales_summary",
            "top_products",
            "sales_by_category",
            "top_shops",
            "sales_by_salesperson",
            "collections",
        ):
            args["period"] = period
        top = _number(r"\btop (\d+)", question)
        if top:
            args["limit"] = min(top, 20)
        if tool == "shops_not_ordering":
            args["days"] = _number(r"(\d+)\s*days?", question) or 30
        if tool == "dues" and re.search(r"overdue", question, re.IGNORECASE):
            args["overdue_only"] = True
        if tool == "product_stock":
            found = _PRODUCT.search(question.strip())
            if not found:
                return "Which product? Ask, for example, “How much stock of Maggi 70g do we have?”"
            args["product"] = found.group("name").strip(" ?.")
        return ToolCall(id=f"call_{tool}", name=tool, args=args)
    return can_answer(offered)


# What each tool lets the person ask about, in the order the fallback reply lists them.
TOPICS = (
    ("sales_summary", "your sales"),
    ("top_products", "top products"),
    ("top_shops", "top shops"),
    ("shops_not_ordering", "shops that stopped ordering"),
    ("low_stock", "low stock"),
    ("product_stock", "a product's stock"),
    ("backorders", "backorders"),
    ("dues", "dues"),
    ("collections", "collections"),
)
EXAMPLES = (
    ("shops_not_ordering", "Which shops haven't ordered in 30 days?"),
    ("low_stock", "Which products are running low?"),
)


def can_answer(offered: set[str]) -> str:
    """The fallback reply: only the topics this person's tools cover."""
    topics = [words for tool, words in TOPICS if tool in offered]
    if not topics:
        return "There are no figures I can show you. Ask the owner if you need them."
    listed = topics[0] if len(topics) == 1 else ", ".join(topics[:-1]) + " and " + topics[-1]
    example = next((text for tool, text in EXAMPLES if tool in offered), None)
    return f"I can answer questions about {listed}." + (
        f" Try \u201c{example}\u201d" if example else ""
    )


_COSTS = re.compile(r"\b(margins?|profits?|costs?|cost price|purchase price)\b", re.IGNORECASE)
_COST_COLUMNS = {"margin", "margin_pct", "cost", "cost_price", "value"}


def costs_note(question: str, figures: dict[str, Any]) -> str:
    """When the question asks for costs or margins the figures don't carry (the person may not
    see them), say so instead of answering around it."""
    if not _COSTS.search(question):
        return ""
    if _COST_COLUMNS & set((figures.get("columns") or {}).keys()):
        return ""
    return "Costs and margins aren't shown to you, so these are the sales figures. "


def _names(rows: list[dict[str, Any]], key: str = "name", n: int = 5) -> str:
    return ", ".join(str(r.get(key, "")) for r in rows[:n])


def write(tool: str, figures: dict[str, Any], args: dict[str, Any]) -> str:
    """A short answer from a tool's figures."""
    rows: list[dict[str, Any]] = figures.get("rows") or []
    totals: dict[str, Any] = figures.get("totals") or {}
    found = figures.get("rows_found", len(rows))
    when = WORDS.get(args.get("period", "this_month"), "")
    mine = " (your shops only)" if figures.get("only_the_askers_own_shops") else ""
    if tool == "sales_summary":
        if not totals or not Decimal(str(totals.get("total") or 0)):
            return f"No sales {when}{mine}."
        return (
            f"Sales {when}{mine}: {rupees(totals.get('total'))} in all, on "
            f"{totals.get('invoices', 0)} invoices; {rupees(totals.get('credited'))} credited."
        )
    if tool in ("top_products", "top_shops", "sales_by_category", "sales_by_salesperson"):
        if not rows:
            return f"No sales {when}{mine}."
        what = {
            "top_products": "Top products",
            "top_shops": "Top shops",
            "sales_by_category": "Sales by category",
            "sales_by_salesperson": "Sales by salesperson",
        }[tool]
        # Net of returns a row can be zero or less; those aren't "top" of anything.
        sold = [r for r in rows if Decimal(str(r.get("total") or 0)) > 0]
        if not sold:
            return f"No sales {when}{mine} after returns."
        lines = [
            f"{i}. {r.get('name')}: {rupees(r.get('total'))}" for i, r in enumerate(sold[:10], 1)
        ]
        return f"{what} {when}{mine}:\n" + "\n".join(lines)
    if tool == "shops_not_ordering":
        days = args.get("days", 30)
        if not rows:
            return f"Every shop{mine} has ordered in the last {days} days."
        never = [r for r in rows if r.get("days_since") is None]
        gone = [r for r in rows if r.get("days_since") is not None]
        parts = [
            f"{found} shop{'s' if found != 1 else ''}{mine} haven't ordered in {days} days or more."
        ]
        if gone:
            parts.append(
                "Longest gaps: "
                + ", ".join(f"{r.get('name')} ({r.get('days_since')} days)" for r in gone[:5])
                + "."
            )
        if never:
            parts.append(f"Never ordered: {_names(never)}.")
        return " ".join(parts)
    if tool == "low_stock":
        if not rows:
            return "Nothing is below its reorder level."
        items = ", ".join(
            f"{r.get('name')} ({quantity(r.get('available'))} left, reorder at "
            f"{quantity(r.get('reorder_level'))})"
            for r in rows[:5]
        )
        return f"{found} product{'s are' if found != 1 else ' is'} low: {items}."
    if tool == "product_stock":
        if not rows:
            return f"I couldn't find a product matching “{args.get('product')}”."
        return " ".join(
            f"{r.get('name')}: {quantity(r.get('available'))} available "
            f"({quantity(r.get('on_hand'))} on hand, "
            f"{quantity(r.get('reserved'))} held for orders)."
            for r in rows[:5]
        )
    if tool == "dues":
        owing = [r for r in rows if Decimal(str(r.get("net") or 0)) > 0]
        if not owing:
            return f"No shop{mine} owes anything."
        top = ", ".join(f"{r.get('name')} {rupees(r.get('net'))}" for r in owing[:5])
        net = Decimal(str(totals.get("net") or 0))
        if net > 0:
            balance = f"Net of credit other shops hold, shops owe {rupees(net)} in all."
        else:  # shops hold more credit than is owed
            balance = (
                f"Counting the credit shops hold, the balance is {rupees(-net)} in their favour."
            )
        return f"Owed the most{mine}: {top}. {balance}"
    if tool == "collections":
        if not rows:
            return f"No payments received {when}{mine}."
        return f"Collected {when}{mine}: {rupees(totals.get('amount'))} in {found} payments."
    if tool == "backorders":
        if not rows:
            return "No shop is waiting for a backorder."
        items = ", ".join(
            f"{r.get('name')} ({quantity(r.get('qty'))} for {r.get('shops')} "
            f"shop{'s' if r.get('shops') != 1 else ''})"
            for r in rows[:5]
        )
        return f"{found} product{'s are' if found != 1 else ' is'} on backorder: {items}."
    return "Here are the figures."


def _units(text: str) -> int:
    return max(1, len(text) // 4)


class ScriptedChat:
    name = "mock"

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        timeout: float,
    ) -> ChatTurn:
        last = messages[-1]
        sent = system + "".join(
            m.text + "".join(r.content for r in m.tool_results) for m in messages
        )
        if last.tool_results:
            call = next(c for m in reversed(messages) for c in m.tool_calls)
            result = last.tool_results[0]
            if result.error:
                reply = "I couldn't get those figures: " + json.loads(result.content).get(
                    "error", ""
                )
            else:
                figures = json.loads(result.content)
                question = next(m.text for m in messages if m.role == "user" and m.text)
                reply = costs_note(question, figures) + write(call.name, figures, call.args)
            return ChatTurn(reply, (), _units(sent), _units(reply), MODEL)
        step = plan(last.text, {t.name for t in tools})
        if isinstance(step, str):
            return ChatTurn(step, (), _units(sent), _units(step), MODEL)
        return ChatTurn("", (step,), _units(sent), 10, MODEL)
