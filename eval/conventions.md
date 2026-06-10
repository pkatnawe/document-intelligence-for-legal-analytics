# Gold-set conventions

The gold files in `gold/*.json` are **hand-verified** from the rendered invoice images (300 dpi),
field by field. These conventions make the labels reproducible and the metric fair.

## What counts as a line item
`line_items` = every **itemized charge or tax/fee row** as printed, **excluding pure summary
rows** (`Subtotal`, `Total`/`Total Paid`/`Grand Total`).

- Itemized tax rows (GST, TVQ, TPS, VAT) **are** line items **and** also populate the `tax`
  field — matching the extraction instruction ("sum tax lines into `tax` AND list each").
- A partial subtotal printed mid-list (e.g. Uber's `Subtotal 34.08` = Base+Distance+Time) is a
  summary row → **excluded** from line items; it populates `subtotal`.
- Consequence: with this convention, **line items sum to the total** for every invoice
  (Uber: 10 rows → 64.46; WeWork: workspace + GST → 36.75; Cargo: 1 row → 99.00). This is also
  why the runtime `reconcile()` check (line-items-vs-total) is a valid correctness signal.

## Per-field rules
- **Money** (`total`, `subtotal`, `tax`, line `amount`): exact value, compared within ±0.01.
  Negative allowed (credit notes).
- **Dates**: stored ISO `YYYY-MM-DD`; the metric normalizes any printed format before comparing.
- **Currency**: stored ISO (`CAD`/`USD`); the metric maps symbols (`CA$`→CAD).
- **`invoice_number`**: only an explicit invoice/receipt id. Ride receipts have **none** → `null`.
  Never a card/phone number, date, or email.
- **`vendor`** = issuer/seller; **`bill_to`** = customer (may be a name or an email).
- **Absent field → `null`.** A model that invents a value is wrong (hallucination), and a model
  that misses a present value is wrong (miss) — both cost score.

## The three documents (why they're a good test)
| Doc | Why it's hard |
|-----|---------------|
| **Uber** | Ride receipt: no invoice number, taxes (TPS/TVQ) mixed into the charge list, a tip that is *not* tax, a partial subtotal, two split payments. |
| **WeWork** | Formal invoice: tax in a summary block (not the line table), redacted region, full billing identity. |
| **Cargo** | Terminal-style receipt: minimal layout, email as `bill_to`, `$0` tax, no `Subtotal` label, USD. |

Three deliberately different layouts → a small but genuinely discriminating gold set. Expand it
by dropping more `gold/*.json` files (and pages) in; the harness picks them up automatically.
