"""E-way bill reasons (kept apart so serializers import no services)."""

# Our reasons; the real adapter maps them to the portal's codes (TODO(verify), items 21-22).
PART_B_REASONS = {
    "BREAKDOWN": "Vehicle broke down",
    "TRANSSHIPMENT": "Transshipment",
    "OTHER": "Other",
}
CANCEL_REASONS = {
    "DUPLICATE": "Duplicate",
    "ORDER_CANCELLED": "Order cancelled",
    "DATA_ENTRY_MISTAKE": "Data entry mistake",
    "OTHER": "Other",
}
