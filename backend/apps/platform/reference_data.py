"""Platform reference data: GST states, GST rate master, default plan, feature flags.

``seed_reference_data`` is idempotent. Migrations call it with historical models; tests call it to
restore the data after a transactional test flushes the tables. Adding a row here needs a new data
migration that calls it again.
"""

from decimal import Decimal
from typing import Any

# TODO(verify): GST state code list as published by GSTN. 25 (Daman & Diu, merged into 26 in 2020)
# and 28 (Andhra Pradesh before 2014) are kept inactive for historical GSTINs.
STATES = [
    ("01", "Jammu and Kashmir", True, True),
    ("02", "Himachal Pradesh", False, True),
    ("03", "Punjab", False, True),
    ("04", "Chandigarh", True, True),
    ("05", "Uttarakhand", False, True),
    ("06", "Haryana", False, True),
    ("07", "Delhi", True, True),
    ("08", "Rajasthan", False, True),
    ("09", "Uttar Pradesh", False, True),
    ("10", "Bihar", False, True),
    ("11", "Sikkim", False, True),
    ("12", "Arunachal Pradesh", False, True),
    ("13", "Nagaland", False, True),
    ("14", "Manipur", False, True),
    ("15", "Mizoram", False, True),
    ("16", "Tripura", False, True),
    ("17", "Meghalaya", False, True),
    ("18", "Assam", False, True),
    ("19", "West Bengal", False, True),
    ("20", "Jharkhand", False, True),
    ("21", "Odisha", False, True),
    ("22", "Chhattisgarh", False, True),
    ("23", "Madhya Pradesh", False, True),
    ("24", "Gujarat", False, True),
    ("25", "Daman and Diu (before 2020)", True, False),
    ("26", "Dadra and Nagar Haveli and Daman and Diu", True, True),
    ("27", "Maharashtra", False, True),
    ("28", "Andhra Pradesh (before 2014)", False, False),
    ("29", "Karnataka", False, True),
    ("30", "Goa", False, True),
    ("31", "Lakshadweep", True, True),
    ("32", "Kerala", False, True),
    ("33", "Tamil Nadu", False, True),
    ("34", "Puducherry", True, True),
    ("35", "Andaman and Nicobar Islands", True, True),
    ("36", "Telangana", False, True),
    ("37", "Andhra Pradesh", False, True),
    ("38", "Ladakh", True, True),
    ("97", "Other Territory", True, True),
]

# ADR-008: GST 2.0 slabs active; 12% and 28% inactive (valid on historical documents only).
TAX_RATES = [
    ("0", True),
    ("0.25", True),
    ("3", True),
    ("5", True),
    ("18", True),
    ("40", True),
    ("12", False),
    ("28", False),
]

FEATURE_FLAGS = [
    ("payments", "Online payments", "Retailers can pay online through a payment gateway."),
    (
        "subscriptions_enforcement",
        "Plan limits",
        "Enforce the plan's limits on retailers, staff and products. "
        "Also needs PLAN_ENFORCEMENT_ENABLED.",
    ),
    (
        "einvoice",
        "E-invoicing",
        "Create IRNs and signed QR codes for invoices through a GST provider.",
    ),
    ("ewaybill", "E-way bills", "Create e-way bills for dispatches through a GST provider."),
    ("whatsapp", "WhatsApp messages", "Send order and payment messages to retailers on WhatsApp."),
    ("batches", "Batches and expiry", "Track stock by batch number and expiry date."),
    ("multi_warehouse", "Multiple warehouses", "Keep stock in more than one warehouse."),
    (
        "purchasing",
        "Purchasing",
        "Suppliers, purchase orders and receiving against them.",
    ),
    (
        "stock_planning",
        "Stock planning",
        "Product demand and classes (ABC, fast and slow), and reorder suggestions.",
    ),
    ("ai", "AI features", "Smart search and the data assistant."),
]


def seed_reference_data(apps: Any) -> None:
    State = apps.get_model("platform", "State")
    TaxRate = apps.get_model("platform", "TaxRate")
    Plan = apps.get_model("platform", "Plan")
    FeatureFlag = apps.get_model("platform", "FeatureFlag")

    for code, name, is_ut, active in STATES:
        State.objects.update_or_create(
            code=code, defaults={"name": name, "is_union_territory": is_ut, "is_active": active}
        )
    for rate, active in TAX_RATES:
        TaxRate.objects.get_or_create(
            rate=Decimal(rate), defaults={"label": f"{rate}%", "is_active": active}
        )
    Plan.objects.get_or_create(
        code="BETA",
        defaults={"name": "Beta", "price_monthly": Decimal("0"), "is_default": True},
    )
    for code, name, description in FEATURE_FLAGS:
        FeatureFlag.objects.get_or_create(
            code=code, defaults={"name": name, "description": description}
        )
