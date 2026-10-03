"""What every import kind provides (ADR-035)."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.utils.functional import Promise
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.dataio.parsing import Sheet
from common.numbers import fill


@dataclass(frozen=True)
class Column:
    name: str  # canonical key
    label: str  # the header in templates and exports, used in messages
    spellings: tuple[str, ...] = ()  # other header texts people use
    required: bool = False  # needed to create a new record
    help: str | Promise = ""  # translated when shown (ADR-060)
    example: str = ""


@dataclass
class RowPlan:
    number: int
    key: str  # product code / mobile number, as typed
    action: str = "NEW"  # NEW, UPDATE, UNCHANGED, ERROR
    problems: list[tuple[str, str]] = field(default_factory=list)  # (column label, message)
    warnings: list[str] = field(default_factory=list)
    changes: dict[str, list[Any]] = field(default_factory=dict)  # label → [old, new]
    highlight: list[str] = field(default_factory=list)  # changed labels to highlight (prices)
    data: dict[str, Any] = field(default_factory=dict)  # clean values to apply
    target_id: Any = None  # existing record for updates

    def error(self, label: str, message: str) -> None:
        """Any problem makes the whole row an error: it is reported, never partly applied."""
        self.problems.append((label, str(message)))
        self.action = "ERROR"

    @property
    def ok(self) -> bool:
        return not self.problems

    def messages(self) -> list[str]:
        return [
            fill(
                _("Row %(row)s, column “%(column)s”: %(message)s"),
                {"row": self.number, "column": label, "message": m},
            )
            for label, m in self.problems
        ]


class Kind(Protocol):
    code: str
    label: str
    permission: str
    key_label: str
    columns: tuple[Column, ...]
    # Column name -> permission needed to see it in templates and exports (e.g. cost price).
    restricted: dict[str, str]

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]: ...

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None: ...

    def export_rows(self) -> Iterable[dict[str, str]]: ...

    def reference_lists(self) -> dict[str, list[str]]: ...
