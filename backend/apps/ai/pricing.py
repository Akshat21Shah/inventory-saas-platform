"""AI use in terms the owner can price (ADR-059 item 8): estimated rupees, and the cap as about
how many assistant questions or shop searches. The provider's units stay the unit of record
(usage rows and the cap); this module only translates them, at today's price settings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from apps.platform.selectors import get_platform_setting

MILLION = Decimal(1_000_000)
PAISE = Decimal("0.01")

# The assistant's model → its price settings (rupees per million units in and out).
MODEL_PRICES = {
    "claude-sonnet-5-5": ("platform.ai_sonnet_price_in", "platform.ai_sonnet_price_out"),
    "claude-haiku-4-5-20251001": ("platform.ai_haiku_price_in", "platform.ai_haiku_price_out"),
}
SEARCH_FEATURES = ("SEARCH_INDEX", "SEARCH_QUERY")


def rupees(amount: Decimal) -> Decimal:
    return amount.quantize(PAISE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Prices:
    model: str
    assistant_in: Decimal  # ₹ per unit
    assistant_out: Decimal
    embeddings: Decimal
    question_in: int  # typical units per assistant question
    question_out: int
    search: int  # typical units per shop search

    def cost(self, feature: str, units_in: int, units_out: int) -> Decimal:
        """Estimated rupees for some use of a feature (not rounded)."""
        if feature in SEARCH_FEATURES:
            return (units_in + units_out) * self.embeddings
        return units_in * self.assistant_in + units_out * self.assistant_out

    @property
    def per_question(self) -> Decimal:
        return self.cost("ASSISTANT", self.question_in, self.question_out)

    @property
    def per_search(self) -> Decimal:
        return self.cost("SEARCH_QUERY", self.search, 0)


def prices(model: str | None = None) -> Prices:
    """Today's prices for ``model`` (default: the assistant's configured model)."""
    chosen = model or str(get_platform_setting("platform.ai_assistant_model"))
    price_in, price_out = MODEL_PRICES.get(chosen, MODEL_PRICES["claude-sonnet-5-5"])

    def per_unit(key: str) -> Decimal:
        return Decimal(str(get_platform_setting(key) or 0)) / MILLION

    return Prices(
        model=chosen,
        assistant_in=per_unit(price_in),
        assistant_out=per_unit(price_out),
        embeddings=per_unit("platform.ai_embeddings_price"),
        question_in=int(get_platform_setting("platform.ai_question_units_in")),
        question_out=int(get_platform_setting("platform.ai_question_units_out")),
        search=int(get_platform_setting("platform.ai_search_units")),
    )


@dataclass(frozen=True)
class Allowance:
    """What a monthly cap of units comes to: about this many questions, or this many searches,
    and at most about this much in rupees (all of it spent on questions, the dearer use)."""

    questions: int
    searches: int
    cost: Decimal


def allowance(limit: int | None, p: Prices) -> Allowance | None:
    if not limit:
        return None
    question_units = p.question_in + p.question_out
    questions = limit // question_units
    return Allowance(
        questions=questions,
        searches=limit // p.search,
        cost=rupees(max(limit * p.per_question / question_units, limit * p.embeddings)),
    )
