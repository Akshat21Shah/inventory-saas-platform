"""GST summary for filing (ADR-050 item 9): a workbook for a month or a quarter laid out like the
GST portal's GSTR-1 Excel template (sheet names, the three summary rows, the header row and the
fixed values copied from the template, ``apps.reports.gst_lists``), for the CA to prepare GSTR-1.

Current defaults, all on the CA's list (questions 31-37) and the checklist (items 26-31):
- B2B: bills to shops with a GSTIN, one row per GST rate; B2C large: bills to shops without one,
  in another state, above ``platform.b2cl_threshold`` (₹1,00,000); B2C others: the rest, by
  place of supply and rate, net of their credit notes.
- Credit notes in the period of their own date: to registered shops note by note (cdnr); to
  unregistered shops against a B2C large bill note by note (cdnur); others netted in B2C others.
- HSN summary in B2B and B2C tabs by HSN, UQC and rate, net of credit notes; the description is
  left blank (the portal fills it from its HSN list).
- Documents issued: the invoice and credit note series used, with bills whose IRN was cancelled
  counted as cancelled (and left out of every other section).
- 0% (nil-rated) lines are left out of the sections and totalled in a note (Table 8's sheet
  layout is still to verify).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import F, Sum

from apps.billing.models import CreditNote, CreditNoteLine, DocumentStatus, Invoice, InvoiceLine
from apps.catalog.models import Unit
from apps.platform.selectors import get_platform_setting
from apps.reports import gst_lists as G
from apps.reports.registry import (
    PERIOD,
    Column,
    Context,
    Group,
    Kind,
    Report,
    Sheet,
    register,
)

FINANCIAL = "reports.financial"
ZERO = Decimal("0")
ISSUED = DocumentStatus.ISSUED
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
QUARTER_STARTS = (4, 7, 10, 1)


def gst_date(day: date) -> str:
    """DD-MMM-YYYY in English whatever the server's locale (the template's format)."""
    return f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year}"


def _month_end(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def check_period(params: dict[str, Any]) -> dict[str, list[str]]:
    """A whole calendar month, or a whole GST quarter (Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar)."""
    start, end = params["date_from"], params["date_to"]
    if start.day != 1:
        return {"date_from": ["Start on the first day of a month."]}
    if end == _month_end(start):
        return {}
    quarter_end = _month_end(date(start.year, start.month, 28) + timedelta(days=62))
    if start.month in QUARTER_STARTS and end == quarter_end:
        return {}
    return {"date_to": ["Choose a whole month or a whole quarter."]}


def _pos(code: str) -> str:
    return G.PLACE_OF_SUPPLY.get(code, code)


def _uqcs() -> dict[str, str]:
    return {
        code: G.UQC.get(uqc, G.OTHER_UQC) for code, uqc in Unit.objects.values_list("code", "uqc")
    }


def _threshold() -> Decimal:
    return Decimal(str(get_platform_setting("platform.b2cl_threshold")))


def _money(value: Any) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


# --- The period's documents ---------------------------------------------------------------------


def _invoices(ctx: Context) -> Any:
    p = ctx.params
    return Invoice.objects.filter(invoice_date__gte=p["date_from"], invoice_date__lte=p["date_to"])


def _notes(ctx: Context) -> Any:
    p = ctx.params
    return CreditNote.objects.filter(
        note_date__gte=p["date_from"], note_date__lte=p["date_to"], status=ISSUED
    )


def _kind(invoice: dict[str, Any], threshold: Decimal) -> str:
    """b2b, b2cl or b2cs, from the invoice's buyer, supply type and value."""
    if (invoice["buyer"] or {}).get("gstin"):
        return "b2b"
    if invoice["supply_type"] == "INTER" and Decimal(invoice["grand_total"]) > threshold:
        return "b2cl"
    return "b2cs"


def _invoice_rows(ctx: Context) -> dict[str, Any]:
    found: dict[str, Any] = ctx.once("gst", lambda: _collect(ctx))
    return found


def _collect(ctx: Context) -> dict[str, Any]:
    threshold = _threshold()
    invoices = {
        i["id"]: i
        for i in _invoices(ctx)
        .filter(status=ISSUED)
        .values(
            "id",
            "number",
            "invoice_date",
            "grand_total",
            "buyer",
            "supply_type",
            "reverse_charge",
            pos=F("place_of_supply_id"),
        )
    }
    per_rate = (
        InvoiceLine.objects.filter(invoice_id__in=invoices)
        .values("invoice_id", "gst_rate")
        .annotate(
            taxable=Sum("taxable_value"),
            cess=Sum("cess_amount"),
            igst=Sum("igst_amount"),
            cgst=Sum("cgst_amount"),
            sgst=Sum("sgst_amount"),
        )
        .order_by("invoice_id", "gst_rate")
    )
    sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    b2cs: dict[tuple[str, Decimal], dict[str, Decimal]] = defaultdict(
        lambda: {"taxable": ZERO, "cess": ZERO}
    )
    nil: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in per_rate:
        inv = invoices[r["invoice_id"]]
        kind = _kind(inv, threshold)
        registered = kind == "b2b"
        if Decimal(r["gst_rate"]) == 0:
            nil[_nil_key(inv["supply_type"], registered)] += r["taxable"] or ZERO
            continue
        row = {**r, "invoice": inv, "kind": kind}
        if kind == "b2cs":
            key = (inv["pos"], Decimal(r["gst_rate"]))
            b2cs[key]["taxable"] += r["taxable"] or ZERO
            b2cs[key]["cess"] += r["cess"] or ZERO
        sections[kind].append(row)
    notes = _note_rows(ctx, threshold, b2cs, nil)
    return {"sections": sections, "b2cs": b2cs, "notes": notes, "nil": nil}


def _nil_key(supply_type: str, registered: bool) -> str:
    where = "Inter-State" if supply_type == "INTER" else "Intra-State"
    who = "registered" if registered else "unregistered"
    return f"{where} supplies to {who} persons"


def _note_rows(
    ctx: Context,
    threshold: Decimal,
    b2cs: dict[tuple[str, Decimal], dict[str, Decimal]],
    nil: dict[str, Decimal],
) -> dict[str, list[dict[str, Any]]]:
    notes = {
        n["id"]: n
        for n in _notes(ctx).values(
            "id",
            "number",
            "note_date",
            "grand_total",
            "buyer",  # a credit note carries its invoice's buyer, supply type and place
            "supply_type",
            "reverse_charge",
            invoice_total=F("invoice__grand_total"),
            pos=F("place_of_supply_id"),
        )
    }
    per_rate = (
        CreditNoteLine.objects.filter(credit_note_id__in=notes)
        .values("credit_note_id", rate=F("invoice_line__gst_rate"))
        .annotate(taxable=Sum("taxable_value"), cess=Sum("cess_amount"))
        .order_by("credit_note_id", "rate")
    )
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in per_rate:
        note = notes[r["credit_note_id"]]
        kind = _kind(
            {
                "buyer": note["buyer"],
                "supply_type": note["supply_type"],
                "grand_total": note["invoice_total"],
            },
            threshold,
        )
        if Decimal(r["rate"]) == 0:
            nil[_nil_key(note["supply_type"], kind == "b2b")] -= r["taxable"] or ZERO
            continue
        if kind == "b2cs":  # netted in B2C others
            key = (note["pos"], Decimal(r["rate"]))
            b2cs[key]["taxable"] -= r["taxable"] or ZERO
            b2cs[key]["cess"] -= r["cess"] or ZERO
            continue
        out["cdnr" if kind == "b2b" else "cdnur"].append({**r, "note": note})
    return out


# --- Sheets (the template's layout) -------------------------------------------------------------


def _cols(*labels: str) -> tuple[Column, ...]:
    kinds = {
        "Invoice Value": Kind.MONEY,
        "Note Value": Kind.MONEY,
        "Taxable Value": Kind.MONEY,
        "Cess Amount": Kind.MONEY,
        "Total Value": Kind.MONEY,
        "Integrated Tax Amount": Kind.MONEY,
        "Central Tax Amount": Kind.MONEY,
        "State/UT Tax Amount": Kind.MONEY,
        "Total Quantity": Kind.QTY,
        "Total Number": Kind.INT,
        "Cancelled": Kind.INT,
    }
    return tuple(Column(label, label, kinds.get(label, Kind.TEXT), width=18) for label in labels)


def _title(text: str, width: int) -> tuple[Any, ...]:
    """The template's first row: the section's title, and "HELP" in its last column."""
    return (text, *([None] * (width - 2)), "HELP")


def _rate(value: Any) -> Any:
    rate = Decimal(value).normalize()
    return int(rate) if rate == rate.to_integral() else float(rate)


def b2b_sheet(data: dict[str, Any]) -> Sheet:
    rows = [
        {
            "GSTIN/UIN of Recipient": r["invoice"]["buyer"].get("gstin", ""),
            "Receiver Name": r["invoice"]["buyer"].get("name", ""),
            "Invoice Number": r["invoice"]["number"],
            "Invoice date": gst_date(r["invoice"]["invoice_date"]),
            "Invoice Value": _money(r["invoice"]["grand_total"]),
            "Place Of Supply": _pos(r["invoice"]["pos"]),
            "Reverse Charge": "Y" if r["invoice"]["reverse_charge"] else "N",
            "Applicable % of Tax Rate": None,
            "Invoice Type": G.REGULAR_B2B,
            "E-Commerce GSTIN": None,
            "Rate": _rate(r["gst_rate"]),
            "Taxable Value": _money(r["taxable"]),
            "Cess Amount": _money(r["cess"]),
        }
        for r in data["sections"]["b2b"]
    ]
    recipients = len({r["GSTIN/UIN of Recipient"] for r in rows})
    invoices = {r["Invoice Number"]: r["Invoice Value"] for r in rows}
    return Sheet(
        "b2b,sez,de",
        _cols(
            "GSTIN/UIN of Recipient",
            "Receiver Name",
            "Invoice Number",
            "Invoice date",
            "Invoice Value",
            "Place Of Supply",
            "Reverse Charge",
            "Applicable % of Tax Rate",
            "Invoice Type",
            "E-Commerce GSTIN",
            "Rate",
            "Taxable Value",
            "Cess Amount",
        ),
        rows,
        preamble=(
            _title("Summary For B2B, SEZ, DE (4A, 4B, 6B, 6C)", 13),
            (
                "No. of Recipients",
                None,
                "No. of Invoices",
                None,
                "Total Invoice Value",
                None,
                None,
                None,
                None,
                None,
                None,
                "Total Taxable Value",
                "Total Cess",
            ),
            (
                recipients,
                None,
                len(invoices),
                None,
                sum(invoices.values(), ZERO),
                None,
                None,
                None,
                None,
                None,
                None,
                sum((r["Taxable Value"] for r in rows), ZERO),
                sum((r["Cess Amount"] for r in rows), ZERO),
            ),
        ),
    )


def b2cl_sheet(data: dict[str, Any]) -> Sheet:
    rows = [
        {
            "Invoice Number": r["invoice"]["number"],
            "Invoice date": gst_date(r["invoice"]["invoice_date"]),
            "Invoice Value": _money(r["invoice"]["grand_total"]),
            "Place Of Supply": _pos(r["invoice"]["pos"]),
            "Applicable % of Tax Rate": None,
            "Rate": _rate(r["gst_rate"]),
            "Taxable Value": _money(r["taxable"]),
            "Cess Amount": _money(r["cess"]),
            "E-Commerce GSTIN": None,
        }
        for r in data["sections"]["b2cl"]
    ]
    invoices = {r["Invoice Number"]: r["Invoice Value"] for r in rows}
    return Sheet(
        "b2cl",
        _cols(
            "Invoice Number",
            "Invoice date",
            "Invoice Value",
            "Place Of Supply",
            "Applicable % of Tax Rate",
            "Rate",
            "Taxable Value",
            "Cess Amount",
            "E-Commerce GSTIN",
        ),
        rows,
        preamble=(
            _title("Summary For B2CL(5)", 9),
            ("No. of Invoices",),
            (
                len(invoices),
                None,
                sum(invoices.values(), ZERO),
                None,
                None,
                None,
                sum((r["Taxable Value"] for r in rows), ZERO),
                sum((r["Cess Amount"] for r in rows), ZERO),
            ),
        ),
    )


def b2cs_sheet(data: dict[str, Any]) -> Sheet:
    rows = [
        {
            "Type": G.OTHER_THAN_ECOMMERCE,
            "Place Of Supply": _pos(pos),
            "Applicable % of Tax Rate": None,
            "Rate": _rate(rate),
            "Taxable Value": _money(v["taxable"]),
            "Cess Amount": _money(v["cess"]),
            "E-Commerce GSTIN": None,
        }
        for (pos, rate), v in sorted(data["b2cs"].items())
        if v["taxable"] or v["cess"]
    ]
    return Sheet(
        "b2cs",
        _cols(
            "Type",
            "Place Of Supply",
            "Applicable % of Tax Rate",
            "Rate",
            "Taxable Value",
            "Cess Amount",
            "E-Commerce GSTIN",
        ),
        rows,
        preamble=(
            _title("Summary For B2CS(7)", 7),
            (None, None, None, None, "Total Taxable  Value", "Total Cess"),
            (
                None,
                None,
                None,
                None,
                sum((r["Taxable Value"] for r in rows), ZERO),
                sum((r["Cess Amount"] for r in rows), ZERO),
            ),
        ),
    )


def cdnr_sheet(data: dict[str, Any]) -> Sheet:
    rows = [
        {
            "GSTIN/UIN of Recipient": (r["note"]["buyer"] or {}).get("gstin", ""),
            "Receiver Name": (r["note"]["buyer"] or {}).get("name", ""),
            "Note Number": r["note"]["number"],
            "Note Date": gst_date(r["note"]["note_date"]),
            "Note Type": G.CREDIT_NOTE,
            "Place Of Supply": _pos(r["note"]["pos"]),
            "Reverse Charge": "Y" if r["note"]["reverse_charge"] else "N",
            "Note Supply Type": G.REGULAR_B2B,
            "Note Value": _money(r["note"]["grand_total"]),
            "Applicable % of Tax Rate": None,
            "Rate": _rate(r["rate"]),
            "Taxable Value": _money(r["taxable"]),
            "Cess Amount": _money(r["cess"]),
        }
        for r in data["notes"]["cdnr"]
    ]
    notes = {r["Note Number"]: r["Note Value"] for r in rows}
    return Sheet(
        "cdnr",
        _cols(
            "GSTIN/UIN of Recipient",
            "Receiver Name",
            "Note Number",
            "Note Date",
            "Note Type",
            "Place Of Supply",
            "Reverse Charge",
            "Note Supply Type",
            "Note Value",
            "Applicable % of Tax Rate",
            "Rate",
            "Taxable Value",
            "Cess Amount",
        ),
        rows,
        preamble=(
            _title("Summary For CDNR(9B)", 13),
            (
                "No. of Recipients",
                None,
                "No. of Notes",
                None,
                None,
                None,
                None,
                None,
                "Total Note Value",
                None,
                None,
                "Total Taxable Value",
                "Total Cess",
            ),
            (
                len({r["GSTIN/UIN of Recipient"] for r in rows}),
                None,
                len(notes),
                None,
                None,
                None,
                None,
                None,
                sum(notes.values(), ZERO),
                None,
                None,
                sum((r["Taxable Value"] for r in rows), ZERO),
                sum((r["Cess Amount"] for r in rows), ZERO),
            ),
        ),
    )


def cdnur_sheet(data: dict[str, Any]) -> Sheet:
    rows = [
        {
            "UR Type": G.UR_B2CL,
            "Note Number": r["note"]["number"],
            "Note Date": gst_date(r["note"]["note_date"]),
            "Note Type": G.CREDIT_NOTE,
            "Place Of Supply": _pos(r["note"]["pos"]),
            "Note Value": _money(r["note"]["grand_total"]),
            "Applicable % of Tax Rate": None,
            "Rate": _rate(r["rate"]),
            "Taxable Value": _money(r["taxable"]),
            "Cess Amount": _money(r["cess"]),
        }
        for r in data["notes"]["cdnur"]
    ]
    notes = {r["Note Number"]: r["Note Value"] for r in rows}
    return Sheet(
        "cdnur",
        _cols(
            "UR Type",
            "Note Number",
            "Note Date",
            "Note Type",
            "Place Of Supply",
            "Note Value",
            "Applicable % of Tax Rate",
            "Rate",
            "Taxable Value",
            "Cess Amount",
        ),
        rows,
        preamble=(
            _title("Summary For CDNUR(9B)", 10),
            (
                None,
                "No. of Notes/Vouchers",
                None,
                None,
                None,
                "Total Note Value",
                None,
                None,
                "Total Taxable Value",
                "Total Cess",
            ),
            (
                None,
                len(notes),
                None,
                None,
                None,
                sum(notes.values(), ZERO),
                None,
                None,
                sum((r["Taxable Value"] for r in rows), ZERO),
                sum((r["Cess Amount"] for r in rows), ZERO),
            ),
        ),
    )


HSN_COLUMNS = (
    "HSN",
    "Description",
    "UQC",
    "Total Quantity",
    "Total Value",
    "Rate",
    "Taxable Value",
    "Integrated Tax Amount",
    "Central Tax Amount",
    "State/UT Tax Amount",
    "Cess Amount",
)
HSN_FIGURES = ("qty", "value", "taxable", "igst", "cgst", "sgst", "cess")


def hsn_groups(ctx: Context) -> dict[str, dict[tuple[str, str, Decimal], dict[str, Decimal]]]:
    found: dict[str, dict[tuple[str, str, Decimal], dict[str, Decimal]]] = ctx.once(
        "hsn", lambda: _hsn(ctx)
    )
    return found


def _hsn(ctx: Context) -> dict[str, dict[tuple[str, str, Decimal], dict[str, Decimal]]]:
    uqcs = _uqcs()
    groups: dict[str, dict[tuple[str, str, Decimal], dict[str, Decimal]]] = {
        "b2b": defaultdict(lambda: dict.fromkeys(HSN_FIGURES, ZERO)),
        "b2c": defaultdict(lambda: dict.fromkeys(HSN_FIGURES, ZERO)),
    }
    figures = {
        "qty": Sum("quantity"),
        "value": Sum("line_total"),
        "taxable": Sum("taxable_value"),
        "igst": Sum("igst_amount"),
        "cgst": Sum("cgst_amount"),
        "sgst": Sum("sgst_amount"),
        "cess": Sum("cess_amount"),
    }
    lines = (
        InvoiceLine.objects.filter(invoice__in=_invoices(ctx).filter(status=ISSUED))
        .values("hsn_code", "unit_code", "gst_rate", buyer=F("invoice__buyer"))
        .annotate(**figures)
        .order_by()
    )
    credits = (
        CreditNoteLine.objects.filter(credit_note__in=_notes(ctx))
        .values(
            hsn_code=F("invoice_line__hsn_code"),
            unit_code=F("invoice_line__unit_code"),
            gst_rate=F("invoice_line__gst_rate"),
            buyer=F("credit_note__invoice__buyer"),
        )
        .annotate(**figures)
        .order_by()
    )
    for sign, rows in ((1, lines), (-1, credits)):
        for r in rows:
            tab = "b2b" if (r["buyer"] or {}).get("gstin") else "b2c"
            key = (r["hsn_code"], uqcs.get(r["unit_code"], G.OTHER_UQC), Decimal(r["gst_rate"]))
            for name in HSN_FIGURES:
                groups[tab][key][name] += sign * (r[name] or ZERO)
    return groups


def hsn_sheet(ctx: Context, tab: str) -> Sheet:
    rows = [
        {
            "HSN": hsn,
            "Description": None,
            "UQC": uqc,
            "Total Quantity": v["qty"],
            "Total Value": _money(v["value"]),
            "Rate": _rate(rate),
            "Taxable Value": _money(v["taxable"]),
            "Integrated Tax Amount": _money(v["igst"]),
            "Central Tax Amount": _money(v["cgst"]),
            "State/UT Tax Amount": _money(v["sgst"]),
            "Cess Amount": _money(v["cess"]),
        }
        for (hsn, uqc, rate), v in sorted(hsn_groups(ctx)[tab].items())
        if any(v.values())
    ]
    totals = [sum((r[c] for r in rows), ZERO) for c in HSN_COLUMNS[4:5]]
    return Sheet(
        f"hsn({tab})",
        _cols(*HSN_COLUMNS),
        rows,
        preamble=(
            _title("Summary For HSN(12)", 11),
            (
                "No. of HSN",
                None,
                None,
                None,
                "Total Value",
                None,
                "Total Taxable Value",
                "Total Integrated Tax",
                "Total Central Tax",
                "Total State/UT Tax",
                "Total Cess",
            ),
            (
                len({r["HSN"] for r in rows}),
                None,
                None,
                None,
                totals[0],
                None,
                *[sum((r[c] for r in rows), ZERO) for c in HSN_COLUMNS[6:]],
            ),
        ),
    )


def docs_rows(ctx: Context) -> list[dict[str, Any]]:
    out = []
    for nature, model, day in (
        (G.INVOICES_NATURE, Invoice, "invoice_date"),
        (G.CREDIT_NOTES_NATURE, CreditNote, "note_date"),
    ):
        p = ctx.params
        docs = model.objects.filter(**{f"{day}__gte": p["date_from"], f"{day}__lte": p["date_to"]})
        for series_id in sorted(set(docs.values_list("series_id", flat=True)), key=str):
            numbers = list(
                docs.filter(series_id=series_id).order_by("number").values_list("number", "status")
            )
            out.append(
                {
                    "Nature of Document": nature,
                    "Sr. No. From": numbers[0][0],
                    "Sr. No. To": numbers[-1][0],
                    "Total Number": len(numbers),
                    "Cancelled": sum(1 for _n, status in numbers if status != ISSUED),
                }
            )
    return out


def docs_sheet(ctx: Context) -> Sheet:
    rows = docs_rows(ctx)
    return Sheet(
        "docs",
        _cols("Nature of Document", "Sr. No. From", "Sr. No. To", "Total Number", "Cancelled"),
        rows,
        preamble=(
            _title("Summary of documents issued during the tax period (13)", 5),
            (None, None, None, "Total Number", "Total Cancelled"),
            (
                None,
                None,
                None,
                sum(r["Total Number"] for r in rows),
                sum(r["Cancelled"] for r in rows),
            ),
        ),
    )


def sheets(ctx: Context) -> list[Sheet]:
    data = _invoice_rows(ctx)
    return [
        b2b_sheet(data),
        b2cl_sheet(data),
        b2cs_sheet(data),
        cdnr_sheet(data),
        cdnur_sheet(data),
        hsn_sheet(ctx, "b2b"),
        hsn_sheet(ctx, "b2c"),
        docs_sheet(ctx),
    ]


# --- On screen: one row per section -------------------------------------------------------------

SECTION_LABELS = {
    "b2b": "B2B invoices (4A)",
    "b2cl": "B2C large invoices (5)",
    "b2cs": "B2C others (7)",
    "cdnr": "Credit notes, registered (9B)",
    "cdnur": "Credit notes, unregistered (9B)",
}


def summary_rows(ctx: Context) -> list[dict[str, Any]]:
    data = _invoice_rows(ctx)
    out = []
    for kind in ("b2b", "b2cl"):
        rows = data["sections"][kind]
        out.append(
            {
                "section": SECTION_LABELS[kind],
                "documents": len({r["invoice"]["id"] for r in rows}),
                "taxable": _money(sum((r["taxable"] or ZERO for r in rows), ZERO)),
                "tax": _money(
                    sum(
                        (
                            (r["igst"] or ZERO) + (r["cgst"] or ZERO) + (r["sgst"] or ZERO)
                            for r in rows
                        ),
                        ZERO,
                    )
                ),
                "cess": _money(sum((r["cess"] or ZERO for r in rows), ZERO)),
            }
        )
    b2cs = data["b2cs"]
    out.append(
        {
            "section": SECTION_LABELS["b2cs"],
            "documents": len({r["invoice"]["id"] for r in data["sections"]["b2cs"]}),
            "taxable": _money(sum((v["taxable"] for v in b2cs.values()), ZERO)),
            "tax": None,
            "cess": _money(sum((v["cess"] for v in b2cs.values()), ZERO)),
        }
    )
    for kind in ("cdnr", "cdnur"):
        rows = data["notes"][kind]
        out.append(
            {
                "section": SECTION_LABELS[kind],
                "documents": len({r["note"]["id"] for r in rows}),
                "taxable": _money(sum((r["taxable"] or ZERO for r in rows), ZERO)),
                "tax": None,
                "cess": _money(sum((r["cess"] or ZERO for r in rows), ZERO)),
            }
        )
    return out


def summary_notes(ctx: Context) -> list[str]:
    data = _invoice_rows(ctx)
    threshold = _threshold()
    notes = [
        f"B2C large: bills to shops without a GSTIN in another state above ₹{threshold:,.2f}. "
        "Credit notes on other B2C bills are netted in B2C others. To be confirmed by your CA.",
    ]
    nil = {k: v for k, v in data["nil"].items() if v}
    if nil:
        parts = ", ".join(f"{k} ₹{_money(v):,}" for k, v in sorted(nil.items()))
        notes.append(f"Nil-rated (0%) supplies, not in these sections (Table 8): {parts}.")
    return notes


register(
    Report(
        code="gst_summary",
        title="GST summary (GSTR-1)",
        group=Group.GST,
        description="Sales in the layout of the GSTR-1 Excel template, for your CA.",
        permission=FINANCIAL,
        columns=(
            Column("section", "Section", width=32),
            Column("documents", "Documents", Kind.INT, total=True, width=10),
            Column("taxable", "Taxable value", Kind.MONEY, total=True),
            Column("tax", "IGST + CGST + SGST", Kind.MONEY, total=True),
            Column("cess", "Cess", Kind.MONEY, total=True),
        ),
        filters=PERIOD,
        rows=summary_rows,
        notes=summary_notes,
        sheets=sheets,
        pdf=True,
        max_days=92,
        check=check_period,
    )
)
