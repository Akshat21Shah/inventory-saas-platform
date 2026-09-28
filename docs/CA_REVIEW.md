# GST invoicing: how the software works, for review by a Chartered Accountant

**Prepared for:** the Chartered Accountant reviewing the platform before it goes live.
**Status:** draft for review (September 2026). Nothing here is live yet. Until you confirm, the
software uses the defaults described below.

**How to read this document.** Each section explains one rule in plain words, with worked examples
in rupees that come from the software itself. Settings a distributor can change are marked
*(setting)*, with the default named. Section 14 lists the questions we would like you to answer
with a yes or no (and a note where needed). Sample documents are in `docs/ca/`:
`sample-invoice.pdf` and `sample-credit-note.pdf`.

---

## 1. The business in one paragraph

A distributor (the supplier, GST-registered under the regular scheme) sells goods to shops
(retailers) in India. Shops order from a phone app; the distributor accepts, packs and dispatches.
The software issues the tax invoice, credit notes and payment receipts, and keeps each shop's
account (ledger). All amounts are handled as exact decimals, never as approximate numbers, and
every document adds up to the paisa.

---

## 2. When the tax invoice is issued

The distributor chooses one of two moments *(setting; default "at dispatch")*. The choice in force
when the order is placed stays with that order.

| Setting | When the invoice is issued | What it covers |
|---|---|---|
| **At dispatch** (default) | When the goods leave the warehouse | Exactly what was packed and dispatched |
| At acceptance | When the order (or a later part of it) is accepted | What was accepted; anything not supplied later is corrected by a credit note |

- An order can be supplied in several parts (for example, some items now and the rest when stock
  arrives). **Each part gets its own invoice.**
- With "at dispatch", if fewer goods are packed than ordered, the invoice simply shows the packed
  quantity, and the rest waits for stock or is cancelled.
- With "at acceptance", a shortfall found at packing is corrected automatically by a **credit
  note** (reason: short supply), marked "Issued automatically".
- **Order Confirmation.** When an order is accepted, the shop can receive an "Order Confirmation"
  listing items, prices and a tax estimate. It carries the line **"This is not a tax invoice."**
  and has no invoice number.

---

## 3. CGST + SGST, or IGST

The software compares two states:

- the **distributor's registered state** (from its GSTIN), and
- the **place of supply** = the state of the shop's **delivery (shipping) address** chosen on the
  order. If the shop has no separate delivery address, its registered (billing) state is used.

| Same state? | Tax charged |
|---|---|
| Yes | CGST + SGST, each at half the rate (for 18%: 9% + 9%) |
| No | IGST at the full rate (18%) |

The place of supply (state name and code) is printed on the invoice. The distributor cannot switch
this rule off.

**Example 1: same state (Maharashtra to Maharashtra).** 10 pieces × ₹123.45, GST 18%.

| Taxable value | CGST 9% | SGST 9% | Line total |
|---|---|---|---|
| ₹1,234.50 | ₹111.11 | ₹111.11 | ₹1,456.72 |

(9% of ₹1,234.50 is ₹111.105; each half is rounded to ₹111.11. See section 5.)

**Example 2: different state (Maharashtra to Gujarat).** The same line.

| Taxable value | IGST 18% | Line total |
|---|---|---|
| ₹1,234.50 | ₹222.21 | ₹1,456.71 |

Note the one-paisa difference: two rounded halves (₹111.11 + ₹111.11 = ₹222.22) against one
rounded whole (₹222.21). This is expected and each invoice is internally consistent.

---

## 4. Discounts reduce the taxable value

Discounts are **trade discounts shown on the invoice**, deducted before tax. Tax is calculated on
the value after discount. The invoice shows the gross amount, the discount and the taxable value
as separate columns.

Two kinds of discount exist:

- **Percentage** (for example 7.5% off).
- **Flat per unit** (for example ₹1.50 off each unit when buying 24 or more). A flat discount is
  never allowed to exceed the line's gross amount.

When several discount schemes apply to one line, the distributor chooses how they combine
*(setting; default "best single scheme")*; either way, one discount amount results for the line,
and that amount is printed.

**Example 3: 7.5% discount, same state.** 24 × ₹57.50, GST 5%.

| Gross | Discount 7.5% | Taxable value | CGST 2.5% | SGST 2.5% | Line total |
|---|---|---|---|---|---|
| ₹1,380.00 | ₹103.50 | ₹1,276.50 | ₹31.91 | ₹31.91 | ₹1,340.32 |

**Example 4: flat discount, different state.** 36 × ₹42.00, GST 18%, ₹1.50 off per unit.

| Gross | Discount (36 × ₹1.50) | Taxable value | IGST 18% | Line total |
|---|---|---|---|---|
| ₹1,512.00 | ₹54.00 | ₹1,458.00 | ₹262.44 | ₹1,720.44 |

---

## 5. Tax on each line, and rounding each tax to the paisa

- Tax is calculated **line by line**, on each line's taxable value, at that line's rate.
- Each tax amount on each line (CGST, SGST, IGST, and cess where it applies) is rounded to the
  paisa **separately**. CGST and SGST are each calculated at half the rate and rounded, so they are
  always equal on a line.
- The invoice totals (total taxable value, total CGST, total SGST, total IGST) are **the sums of
  the line amounts**. They are never recalculated from the totals.
- The HSN-wise summary on the invoice is also the sum of the lines, grouped by HSN code and rate.

How a half paisa is rounded *(setting; default "half up")*:

| Option | ₹111.105 becomes | ₹111.115 becomes |
|---|---|---|
| **Half up** (default) | ₹111.11 | ₹111.12 |
| Half to even ("banker's rounding") | ₹111.10 | ₹111.12 |

**Example 5: several rates on one invoice, same state.**

| # | Line | GST | Taxable value | CGST | SGST | Line total |
|---|---|---|---|---|---|---|
| 1 | 10 × ₹123.45 | 18% | ₹1,234.50 | ₹111.11 | ₹111.11 | ₹1,456.72 |
| 2 | 24 × ₹57.50, 7.5% off | 5% | ₹1,276.50 | ₹31.91 | ₹31.91 | ₹1,340.32 |
| 3 | 2.750 kg × ₹180.00 | 0% | ₹495.00 | ₹0.00 | ₹0.00 | ₹495.00 |
| 4 | 5 × ₹999.99 | 12% | ₹4,999.95 | ₹300.00 | ₹300.00 | ₹5,599.95 |
| | **Totals** | | **₹8,005.95** | **₹443.02** | **₹443.02** | **₹8,891.99** |

Invoice total ₹8,892.00 with a round-off of +₹0.01 (section 6).

(Line 4: 6% of ₹4,999.95 is ₹299.997, rounded to ₹300.00.)

---

## 6. Invoice total and the round-off line

*(Setting; default: round the total to the nearest rupee.)* The software adds up the line totals,
rounds the result to a whole rupee, and prints the difference as a separate **round-off** line.
The round-off is always less than one rupee.

| Option | Line totals ₹1,456.72 | Line totals ₹1,000.50 | Line totals ₹1,000.49 |
|---|---|---|---|
| **Nearest rupee** (default; exactly 50 paise goes up) | ₹1,457.00 (round-off +₹0.28) | ₹1,001.00 (+₹0.50) | ₹1,000.00 (−₹0.49) |
| Always up | ₹1,457.00 (+₹0.28) | ₹1,001.00 (+₹0.50) | ₹1,001.00 (+₹0.51) |
| Always down | ₹1,456.00 (−₹0.72) | ₹1,000.00 (−₹0.50) | ₹1,000.00 (−₹0.49) |
| Rounding switched off | ₹1,456.72 (no round-off) | ₹1,000.50 | ₹1,000.49 |

The complete Example 1 line under each combination of settings:

| Each tax rounded | Line total | Total rounded | Invoice total | Round-off |
|---|---|---|---|---|
| Half up (default) | ₹1,456.72 | Nearest (default) | ₹1,457.00 | +₹0.28 |
| Half up | ₹1,456.72 | Always down | ₹1,456.00 | −₹0.72 |
| Half up | ₹1,456.72 | Always up | ₹1,457.00 | +₹0.28 |
| Half up | ₹1,456.72 | Off | ₹1,456.72 | ₹0.00 |
| Half to even | ₹1,456.70 (CGST = SGST = ₹111.10) | Nearest | ₹1,457.00 | +₹0.30 |

The rounding settings in force when an invoice is issued are stored with that invoice, so a later
change of setting never alters an issued invoice.

---

## 7. Prices that already include GST

*(Setting; default: prices exclude GST.)* Some distributors quote prices that include GST. In that
case the software works backwards on each line:

1. Gross amount including GST, minus any discount (on the including-GST amount).
2. Taxable value = that amount × 100 ÷ (100 + rate), rounded to the paisa.
3. Tax on the taxable value, rounded as in section 5.

The invoice then shows the taxable value and tax in the usual way. Whether an order's prices
include GST is fixed when the order is placed.

**Example 6: exact.** 3 × ₹49.99 including 18%, same state.
₹149.97 × 100 ÷ 118 = ₹127.0932 → taxable ₹127.09; CGST 9% = ₹11.44; SGST ₹11.44; line total
₹149.97, exactly the displayed amount.

**Example 7: one paisa short.** 1 × ₹7.00 including 18%, same state.
₹7.00 × 100 ÷ 118 = ₹5.9322 → taxable ₹5.93; CGST ₹0.53; SGST ₹0.53; line total **₹6.99**. The
invoice round-off (+₹0.01) brings the amount payable back to **₹7.00**. The software accepts a
difference of at most one paisa per line, always absorbed this way.

**Example 8: with a discount.** 10 × ₹118.00 including 18%, 10% off, same state.
Gross ₹1,180.00 − discount ₹118.00 = ₹1,062.00 → taxable ₹900.00. Shown excluding GST: gross
₹1,000.00, discount ₹100.00, taxable ₹900.00; CGST ₹81.00; SGST ₹81.00; line total ₹1,062.00.

---

## 8. GST rate changes

- Each product has a GST rate with a start date. When the government changes a rate, the new rate
  is entered with its start date in advance.
- An invoice uses **the rate valid on the invoice date**, not the rate when the order was placed.
  If they differ, the line is flagged and the distributor sees a warning.
- A credit note always uses the rate of **the invoice it corrects**, even if the rate has changed
  since.

**Example 11.** An order placed on 20 September at 12% (estimate). The rate becomes 5% from
22 September. Dispatched and invoiced on 23 September → the invoice charges **5%** and the line
shows "rate differs from the order". A credit note on 1 October against that invoice uses 5%; a
credit note against an older invoice issued at 12% uses 12%.

---

## 9. Credit notes

A credit note is the only way to correct an issued invoice. Invoices are never edited or deleted.
Each credit note refers to one invoice and has its own number series (section 10).

| Kind | Who issues it | What it covers |
|---|---|---|
| **Return** | Distributor staff | Goods sent back by the shop, chosen line by line with quantities |
| **Short supply** | Automatic ("at acceptance" invoicing only) | Invoiced goods that could not be supplied |
| **Cancellation** | Automatic ("at acceptance" invoicing only) | An invoiced part of an order that was cancelled before dispatch |
| **Price adjustment** | Distributor staff, with a reason | A value correction; no goods move |

For a **return**, a reason is required (damaged, expired, wrong item, excess supply, or other with
a note), and each line records what happened to the goods:

- **Returned to stock** (default): the goods go back into saleable stock.
- **Received damaged**: the goods come back and are written off (both steps are recorded).
- **Not physically returned**: value only; no goods move.

**How tax is worked out on a partial return.** The credit note takes the same share of the
invoice line's taxable value as the share of quantity returned, and works out tax at the invoice
line's rate. The credit note that uses up the rest of a line takes exactly what is left, so the
line is always fully and exactly reversed with no paisa left over.

**Example: return 3, then 7, of Example 1's line** (10 × ₹123.45, 18%, same state; the invoice
line total was ₹1,456.72).

| Credit note | Quantity | Taxable value | CGST | SGST | Line total |
|---|---|---|---|---|---|
| CN 1 | 3 | ₹370.35 (3/10 of ₹1,234.50) | ₹33.33 | ₹33.33 | ₹437.01 |
| CN 2 (the rest) | 7 | ₹864.15 | ₹77.78 | ₹77.78 | ₹1,019.71 |
| **Together** | **10** | **₹1,234.50** | **₹111.11** | **₹111.11** | **₹1,456.72** |

Each credit note is rounded to the rupee like an invoice (CN 1: ₹437.00, round-off −₹0.01). The
credit note that uses up the whole invoice takes the invoice total minus what earlier credit notes
already credited (CN 2: ₹1,457.00 − ₹437.00 = ₹1,020.00), so the shop's balance for that invoice
ends at exactly ₹0.00.

If a credit note is larger than what the shop still owes on that invoice, the difference stays in
the shop's account as a credit and is used for its next invoice.

---

## 10. Numbering

| Document | Example | Rules |
|---|---|---|
| Tax invoice | `INV/26-27/000001` | Per distributor, per financial year (April–March, Indian time), no gaps, restarts at 1 each year |
| Credit note | `CN/26-27/000001` | Separate series, same rules |
| Payment receipt | `RCT/26-27/000001` | Separate series, same rules |

- At most 16 characters, using only capital letters, digits, "/" and "-".
- The distributor may change the prefix (for example `SD` instead of `INV`) within the 16-character
  limit.
- A number is given only when the document is actually issued, inside the same step that saves
  it, so two documents can never share a number and no number is ever skipped.

---

## 11. What the invoice shows

- Title "Tax Invoice" and the copy label (see below).
- Supplier: legal name, trade name, address, GSTIN, state and state code.
- Invoice number and date; due date; order number.
- Recipient (billed to): name, address, GSTIN if registered, state and state code.
- Delivery address (shipped to), when different from the billing address.
- Place of supply (state name and code). Reverse charge: No.
- For each line: description, HSN code, quantity and unit, rate per unit, gross amount, discount,
  taxable value, GST rate, CGST/SGST or IGST amounts, and line total.
- Totals: taxable value, each tax, round-off, amount payable, and the amount in words (Indian
  system: lakh, crore).
- HSN-wise summary of taxable value and tax.
- Bank details for payment, terms, and the authorised signatory.
- When e-invoicing is added later: the IRN, acknowledgement number and date, and the QR code.

**Copies.** GST rules expect an invoice for goods in triplicate. Staff print one PDF with three
labelled copies: "Original for recipient", "Duplicate for transporter" and "Triplicate for
supplier". The shop downloads the original only.

Credit notes show the same details plus the invoice they correct (number and date) and the reason.

---

## 12. Payments, advances and the shop's account (for context)

- Every issued invoice is recorded as an amount owed in the shop's account; every payment and
  credit note reduces it. The account never has entries edited or deleted: a mistake is corrected
  by a new, opposite entry.
- Payments (cash, cheque, bank transfer, UPI) get a numbered receipt. They are set against the
  oldest invoices first unless staff choose otherwise.
- Cheques are credited when received and reversed automatically if they bounce *(setting; the
  alternative is to credit only when cleared)*.
- Money received beyond what is owed is held as an advance and used automatically for the shop's
  next invoices, oldest money first *(setting)*. Receipts are plain payment receipts; no GST is
  charged on them.
- Salesmen may record collections in the field; the shop is credited and gets a receipt at once,
  and the office later confirms the money was handed over.

---

## 13. What is not yet included

- **E-invoicing (IRN) and e-way bills** arrive in a later release. The invoice already has room for
  the IRN, acknowledgement and QR code, so it will not change shape.
- Only regular GST registration is supported (not the composition scheme).
- Cess is supported in the calculation (worked out like GST, on the taxable value) but no demo
  product uses it yet.

---

## 14. Questions for you

Please answer yes or no, with a note where the answer is no.

| # | Question | Yes / No | Note |
|---|---|---|---|
| 1 | Is it acceptable to calculate GST line by line on each line's taxable value, rounding each tax amount (CGST, SGST, IGST) to the paisa separately, and to take the invoice totals as the sums of the lines? | | |
| 2 | Is "half up" the right default for rounding each tax amount to the paisa? | | |
| 3 | Should "half to even" be offered to distributors at all? | | |
| 4 | Is rounding the invoice total to the nearest rupee, with a separate round-off line (always less than one rupee), acceptable? | | |
| 5 | Should the "always up" and "always down" round-off options be offered at all? | | |
| 6 | With GST-inclusive prices, is it acceptable to work out the taxable value line by line, and to absorb a difference of at most one paisa per line in the round-off (Example 7)? | | |
| 7 | Is it correct to treat the discounts described in section 4 (shown on the invoice, deducted before tax) as reducing the taxable value? | | |
| 8 | Is the place of supply correctly taken as the state of the delivery address chosen on the order (or the shop's registered state when there is none)? | | |
| 9 | Is it correct to charge the GST rate valid on the invoice date, even when the rate changed after the order was placed? | | |
| 10 | Is it correct for a credit note to use the rate of the invoice it corrects, even when the rate has changed since? | | |
| 11 | Is working out a partial return's taxable value as the same share of the invoice line (by quantity), with the last credit note taking the exact remainder, acceptable? | | |
| 12 | Is a value-only credit note ("not physically returned", or a price adjustment) acceptable as a GST credit note? | | |
| 13 | With "at acceptance" invoicing, is an automatic credit note the right way to correct goods invoiced but not supplied (short supply, cancellation)? | | |
| 14 | Is issuing the invoice at dispatch, for exactly what was packed, the right default? | | |
| 15 | Are the number formats `INV/26-27/000001`, `CN/26-27/000001` and `RCT/26-27/000001`, with separate series restarting each financial year, acceptable? | | |
| 16 | Does the invoice content in section 11 meet the requirements for a tax invoice for goods? | | |
| 17 | Is one PDF with three labelled copies (original, duplicate, triplicate) for staff, and the original only for the shop, acceptable? | | |
| 18 | For shops without a GSTIN, is the same invoice (name, address, state, no GSTIN) acceptable? | | |
| 19 | Is a plain payment receipt, without GST, acceptable for advances received from shops for goods? | | |
| 20 | Is a minimum of 4 HSN digits on invoices acceptable as the default (distributors can require 6 or 8)? | | |
