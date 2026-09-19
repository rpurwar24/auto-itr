# Statutory form templates

Headers downloaded from the e-filing portal, kept because the portal matches them
**byte-for-byte** - a re-typed or re-ordered header fails the upload with
`csv_header_mismatch`. Data rows are never kept here: they carry real income figures.

## `form67_part_a.csv` - Form 67, Part A

Form 67 claims foreign tax credit under Rule 128 and must be filed **before** the return,
or CPC disallows the FTC. Portal path: e-File -> Income Tax Forms -> Form 67.

Filling it, learned the hard way (AY2026-27):

- The dropdown columns take **exact** strings. A value that doesn't match is **not** an
  upload error - the row imports with that field **blank** and only shows a row error
  afterwards. Two that bite:
  - country: `United States Of America` - capital `Of`
  - source of income: `Dividend`. There is a real Dividend option; it is *not* the ITR's
    "Other Sources" head. The adjacent `Please specify` columns stay EMPTY unless the
    chosen value is "Other".
- `Credit claimed under section 90/90A - Amount` must be non-zero, or the row errors with
  "Value in both fields can not be Zero". The downloaded template has no column for it,
  so key it in through **Edit Detail** after the upload.
- Part B is two questions (carry-backward-of-loss refund, disputed credit); Parts C and D
  are the verification and the attachment.
- Attachment: the broker's **1042-S**, or a year-end summary stating the gross dividend and
  the tax withheld. PDF or zip, 5 MB limit.
- For an individual holding US portfolio stock the DTAA rate is **25%**
  (Art 10(2)(b)); 15% is the corporate rate and does not apply.
