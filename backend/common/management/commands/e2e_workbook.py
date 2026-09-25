"""Write an Excel import file for the end-to-end acceptance test (Phase 2: 1,000 products and 100
retailers) and print it base64-encoded, so the browser test can upload a real .xlsx without a
spreadsheet library of its own. Dev only: refuses unless DEBUG is on.
"""

import base64
import io
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from openpyxl import Workbook

PRODUCT_HEADER = [
    "Product code",
    "Product name",
    "Unit",
    "HSN code",
    "GST rate",
    "Price",
    "MRP",
    "Category",
    "Brand",
]
RETAILER_HEADER = [
    "Mobile",
    "Shop name",
    "Owner name",
    "State",
    "Address",
    "City",
    "PIN code",
    "Price list",
]
CATEGORIES = ["Food > Biscuits", "Food > Snacks", "Beverages > Tea", "Home care > Detergent"]
BRANDS = ["Acme", "Globex", "Initech", "Umbrella"]


def products(count: int, prefix: str) -> list[list[Any]]:
    rows: list[list[Any]] = [PRODUCT_HEADER]
    for n in range(1, count + 1):
        price = 10 + n % 90
        rows.append(
            [
                f"{prefix}-{n:04d}",
                f"{prefix} Product {n:04d}",
                "PCS",
                "1905",
                "18%",
                f"₹{price:,}.50",  # as typed in Excel: symbol and separators
                price * 2,
                CATEGORIES[n % len(CATEGORIES)],
                BRANDS[n % len(BRANDS)],
            ]
        )
    return rows


def retailers(count: int, first_phone: int, price_list: str) -> list[list[Any]]:
    rows: list[list[Any]] = [RETAILER_HEADER]
    for n in range(1, count + 1):
        rows.append(
            [
                str(first_phone + n),
                f"E2E Shop {n:03d}",
                f"Owner {n:03d}",
                "Maharashtra",
                f"Shop {n}, Market Road",
                "Pune",
                "411001",
                price_list if n % 2 else "",  # every other shop is on the price list
            ]
        )
    return rows


class Command(BaseCommand):
    help = "Print a base64 .xlsx import file for the E2E acceptance test."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("kind", choices=["products", "retailers"])
        parser.add_argument("--count", type=int, default=1000)
        parser.add_argument("--prefix", default="E2E")
        parser.add_argument("--first-phone", type=int, default=9_811_100_000)
        parser.add_argument("--price-list", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("e2e_workbook only runs with DEBUG=True")
        rows = (
            products(options["count"], options["prefix"])
            if options["kind"] == "products"
            else retailers(options["count"], options["first_phone"], options["price_list"])
        )
        book = Workbook()
        sheet = book.active
        assert sheet is not None
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        book.save(buffer)
        self.stdout.write(base64.b64encode(buffer.getvalue()).decode())
