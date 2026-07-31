# FX data - SBI TTBR (Rule 115)

`sbi_ttbr_monthly.csv` holds the **SBI Telegraphic-Transfer BUYING rate** (USD -> INR),
one row per month, equal to the rate **as on that month's last working day**.

Rule 115 (for capital gains): convert using the TTBR on the **last day of the month
immediately preceding** the month of transfer.
So a sale on 2025-09-18 uses the row for `2025-08`.

## Populating this file
Use an authoritative SBI TTBR source. Options (to be decided with the user):
- SBI's published daily TT/Bill rate card (take the last working day of each month).
- A maintained TTBR dataset / the value the user's CA uses.

Do NOT fabricate rates - every rupee in the return depends on these.

## Why not reuse .numbers / Adobe rates?
- `.numbers` used exchangerates.org.uk (not SBI TTBR) - fine for reproducing FILED returns
  via `NumbersRateSource`, but not the statutory rate going forward.
- Adobe's perquisite-statement forex is Adobe's own rate, used only for the Form 16
  perquisite value.
The going-forward return uses SBI TTBR (`SbiTtbrSource`), per the user's decision.
