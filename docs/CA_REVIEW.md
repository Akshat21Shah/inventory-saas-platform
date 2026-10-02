# GST invoicing: how the software works, for review by a Chartered Accountant

**Prepared for:** the Chartered Accountant reviewing the platform before it goes live.
**Status:** draft for review (September 2026). Nothing here is live yet. No CA is engaged yet:
this pack is reviewed in one go once every feature is built, before launch. Until you confirm, the
software uses the defaults described below.

**How to read this document.** Each section explains one rule in plain words, with worked examples
in rupees that come from the software itself. Settings a distributor can change are marked
*(setting)*, with the default named. Section 16 lists the questions we would like you to answer
with a yes or no (and a note where needed). Sample documents are in `docs/ca/`:
`sample-invoice.pdf` (Example 5 in section 5, as the shop receives it),
`sample-invoice-copies.pdf` (the same invoice in the three labelled copies staff print) and
`sample-credit-note.pdf` (CN 1 in section 9: 3 of the first line returned damaged). They are
printed by the software from the same figures; the business names and GSTINs are made up.

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
- A receipt is numbered in the financial year in which it is recorded, but the payment is dated
  and accounted on the day it was actually received. A payment received on 30 March and recorded
  on 2 April gets a number in the new year's series (`RCT/27-28/…`) and appears in the shop's
  account on 30 March; staff see a warning that it belongs to the earlier year.
- Old bills from before the software carry their original bill date and due date, so they age
  and become overdue like invoices.
- A shop's credit balance can be paid back by a numbered refund voucher (`RFD/26-27/000001`),
  never more than the credit the shop has.

---

## 13. What is not yet included

- **E-invoicing (IRN) and e-way bills** are described in section 14; they are switched on per
  distributor and stay off until then.
- Only regular GST registration is supported (not the composition scheme).
- Cess is supported in the calculation (worked out like GST, on the taxable value) but no demo
  product uses it yet.

---

## 14. E-invoicing, e-way bills and online payments

These modules are off unless we switch them on for a distributor; with them off, nothing in
sections 2 to 12 changes. The software talks to the GST system through a GST Suvidha Provider
(GSP), which is not chosen yet, so the rules below are our current understanding and are also on
our technical checklist.

**E-invoicing (IRN).**
- The distributor tells us its annual turnover band: below ₹5 crore, ₹5–10 crore, or ₹10 crore and
  above *(setting)*. From ₹5 crore we suggest switching e-invoicing on; from ₹10 crore we also warn
  when an invoice is close to the reporting limit (taken as 30 days from the invoice date).
- IRNs are obtained for tax invoices to shops with a GSTIN, and for their credit notes. Shops
  without a GSTIN (B2C) get no IRN.
- The IRN is requested automatically when the invoice is issued *(setting: or by staff, one at a
  time)*. The invoice PDF then shows the IRN, acknowledgement number and date, and the signed QR
  code. The message sending the bill to the shop waits for the IRN, at most 10 minutes.
- If the GST system refuses the invoice (for example, an invalid GSTIN), the invoice stays in our
  books, marked "IRN failed", so staff can correct the shop's details and try again.
- **Cancelling an IRN** is possible only within the permitted window (taken as 24 hours), with a
  reason. Staff then choose: (a) *default:* issue a corrected invoice with a new number for the
  same shipment, or (b) take the goods back. Either way the cancelled invoice is reversed in the
  shop's account with a reversing entry, and its number is never reused. After the window, the only
  correction is a credit note (section 9).

**E-way bills.**
- An e-way bill is generated at dispatch when the consignment value (invoice value including tax)
  is above the threshold: one for goods going to another state and one within the state, both
  ₹50,000 by default *(settings)*.
- The distance comes from the shop's address and can be changed at dispatch. The vehicle can be
  updated later (Part-B). Dispatch never waits for the e-way bill; failures are shown to staff.

**Online payments.**
- Shops can pay online (UPI, cards, net banking) through the distributor's own payment gateway
  account; money settles to the distributor. A payment counts only when the gateway confirms it to
  us directly, never on the shop's screen alone.
- It is recorded like any other payment, with a receipt, on the date the gateway captured it
  (not the date the gateway settles it to the bank), and allocated to the oldest bills first, or to
  the bill the shop chose. Gateway fees are the distributor's cost and are not shown to the shop.
- If more is paid than is owed, the excess is kept as the shop's credit (an advance), as for
  cheques.

---

## 15. Reports for GST filing, and the export to your accounts (Tally)

**GST summary for filing (built in Phase 8).** For a month, or a quarter for quarterly filers, the
software produces a workbook laid out like the official GSTR-1 Excel template, for you to prepare
the return. It is a summary of what the software issued; the return itself is filed by you.
- **B2B:** each invoice to a shop with a GSTIN, one row per GST rate on the invoice (invoice number,
  date, value, place of supply, taxable value, rate, taxes).
- **B2C large:** invoices to shops without a GSTIN in another state above ₹1,00,000 *(platform
  setting; the limit was reduced from ₹2,50,000 from August 2024)*, invoice by invoice.
- **B2C others:** all other sales to shops without a GSTIN, totalled by rate and place of supply.
- **Credit notes:** to registered shops note by note; to unregistered shops as the template requires.
- **HSN summary:** in two tabs, B2B and B2C (the portal's split from May 2025), by HSN code, unit
  (UQC), quantity, values and taxes per rate.
- **Documents issued:** the invoice and credit note series used in the period, with counts of
  cancelled documents.
- Invoices whose IRN was cancelled (section 14) are left out of the sections above and counted as
  cancelled; the corrected invoice issued in their place is reported normally.
- Credit notes are reported in the period of their own date, not the invoice's.

**Export to Tally (designed, not built yet).** Many distributors keep their books in TallyPrime.
The plan is an export file Tally can import: our sales invoices as Sales vouchers, credit notes as
Credit Note vouchers and receipts as Receipt vouchers, as accounting entries without stock items.
- Each voucher carries our document number and date, the shop as the party, and a bill reference
  (a new reference for an invoice; against the invoice for a credit note or a receipt).
- The distributor names its Tally ledgers once: the shop's ledger (default: the shop's name, with an
  optional file to create the shop ledgers first, including GSTIN, state and address), the sales
  ledger (one, or one per GST rate), the output CGST, SGST, IGST and cess ledgers, round-off, and
  the cash and bank ledgers for each payment mode.
- Tally's own guidance is that a file must match what TallyPrime itself exports for the same voucher.
  So before building it we would ask you to create one sample Sales, Credit Note and Receipt voucher
  in your TallyPrime, export them as XML and send them to us. The export stays labelled "beta" until
  a real import succeeds.

---

## 15a. Free-goods schemes ("buy X get Y free"; Phase 9b, switched on per distributor)

A distributor can run a scheme such as "buy 10 packets, get 1 free" (the same product or another).
How the platform shows it today:

- The shop pays for the 10 packets at their usual price, with any usual discount; the GST on them
  is worked out as for any line.
- The free packet is a separate line on the invoice at ₹0: quantity, HSN and "Free (scheme)", a
  taxable value of 0 and no GST.
- If the shop returns some of the packets, staff may take free packets back too, at ₹0 (stock comes
  back; nothing is charged).
- Free packets sent later on their own (out of stock at first) get their own ₹0 invoice; free
  packets alone coming back, or not supplied after invoicing, get a ₹0 credit note.
- Stock and the margin report count the free packets at their cost.

We understand CBIC Circular 92/11/2019-GST to treat "buy one get one free" offers as one supply
for the price charged, with input tax credit not reversed; please confirm or correct (questions
41–46).

---

## 16. Questions for you

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
| 21 | Receipt numbered in the year it is recorded, but dated and accounted on the actual payment date — acceptable? | | |
| 22 | Is a refund voucher in its own series (`RFD/26-27/000001`), paying back a shop's credit balance by cash, bank transfer or UPI, acceptable? | | |
| 23 | Is it correct that e-invoicing applies from an aggregate turnover above ₹5 crore (in any year since 2017-18), and that the distributor declaring its turnover band is a reasonable basis for our suggestion? | | |
| 24 | Are IRNs needed only for B2B tax invoices and their credit notes (not for B2C invoices)? | | |
| 25 | Is the reporting limit of 30 days from the invoice date, for businesses with turnover of ₹10 crore and above, still correct? | | |
| 26 | Within the cancellation window (taken as 24 hours), is cancelling the IRN and issuing a corrected invoice with a new number for the same goods acceptable, with the cancelled number never reused? | | |
| 27 | When an IRN cannot be obtained (the GST system refuses or is down), is it acceptable to keep the invoice in our books, marked "IRN failed", and retry after correction? What should the distributor do about goods already dispatched? | | |
| 28 | Is the e-way bill consignment value correctly taken as the invoice value including tax, and is ₹50,000 the right default for both inter-state and intra-state movement (knowing some states set their own limit)? | | |
| 29 | Is recording an online payment on the date the gateway captured it (not the settlement date), with the gateway's fee outside the shop's account, acceptable? | | |
| 30 | When an invoice's IRN is cancelled and the invoice re-issued for the same supply, should the re-issued invoice use the original tax rates or those valid on the new invoice date? (It currently keeps the original rates, and warns staff when today's rate differs.) | | |
| 31 | Is a workbook laid out like the official GSTR-1 Excel template (B2B, B2C large, B2C others, credit notes, HSN summary in B2B and B2C tabs, documents issued; section 15) what you need to prepare GSTR-1? Is any other table needed for this business (for example nil-rated or exempt supplies, or advances received)? | | |
| 32 | Is it correct that invoices to unregistered buyers in another state above ₹1,00,000 are reported invoice by invoice (B2C large), and all other B2C supplies are totalled by rate and place of supply? | | |
| 33 | HSN summary: separate B2B and B2C tabs, the HSN code at the digits the distributor requires on products (4 by default), and the unit's UQC — correct? Should the description be the product's or the HSN's official description? | | |
| 34 | Which credit notes to unregistered buyers must be reported note by note, and which are simply netted in B2C others? | | |
| 35 | Invoices whose IRN was cancelled: left out of B2B and the HSN summary and counted as cancelled under documents issued, with the corrected invoice reported normally — correct? | | |
| 36 | Documents issued: should it list only tax invoices and credit notes (not payment receipts or refund vouchers)? | | |
| 37 | For quarterly (QRMP) filers, is one workbook for the quarter useful, or should the monthly B2B invoices (IFF) come separately? | | |
| 38 | **Can you test a Tally import?** Do you use TallyPrime for the distributor's books, and could you export one sample Sales, Credit Note and Receipt voucher from it as XML and later test importing our file (section 15)? | | |
| 39 | Tally: are accounting entries without stock items right for importing sales? One sales ledger, or one per GST rate? Output tax ledgers per tax (CGST, SGST, IGST, cess) or per rate as well? Shop ledgers under Sundry Debtors named as the shop? | | |
| 40 | Tally: how should an invoice whose IRN was cancelled appear — as a cancelled voucher, or left out with only the corrected invoice exported? And receipts: one bank ledger per payment mode (cash, cheque, UPI, bank transfer, online gateway), with gateway fees entered by the distributor separately? | | |
| 41 | Free-goods schemes: is it right to invoice the free goods as a separate ₹0 line (quantity, HSN, "Free (scheme)") with no GST, the GST being charged only on the price of the goods bought? | | |
| 42 | Should the free goods instead appear on the bought line (e.g. "10 + 1 free" at the price of 10), or should the price be spread over all the goods (a discount in kind)? | | |
| 43 | Input tax credit: may the distributor keep the input tax credit on goods given free under such a scheme (no reversal)? | | |
| 44 | E-invoices and GSTR-1: should the free goods go in the IRN as their own ₹0 item, or in the bought item's free-quantity field; and do they count in the HSN summary's quantities? | | |
| 45 | Returns: when a shop returns goods bought under a scheme, must the free goods given with them be returned or charged, or may the distributor let the shop keep them? | | |
| 46 | When the free goods are sent later on their own (the bought goods went earlier, the free ones were out of stock), the platform issues a ₹0 tax invoice for them, and a ₹0 credit note when free goods alone come back or are not supplied. Is a ₹0 tax invoice right here, or should it be a delivery challan? | | |
| 47 | Cheque bounce charges: a distributor may charge a shop a fixed amount when its cheque bounces. We post it as a debit with no GST, on the understanding that a penalty for a dishonoured cheque is not consideration for a supply (CBIC Circular 178/10/2022-GST). Is that right, or should it be a GST invoice? | | |
