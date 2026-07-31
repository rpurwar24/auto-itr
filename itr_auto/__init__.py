"""ITR-2 automation package.

Pipeline layers:
  1. parsers   - raw source docs (Form 16, ESOP HTML, trade confirmations) -> facts
  2. reference - FX service (SBI TTBR / Rule 115) + the vest-lot ledger
  3. compute   - per-schedule engines (S, FA, CG, OS, TCS, AL, ...)
  4. assemble  - map computed values into the ITR-2 JSON schema

See CLAUDE.md for the domain model and ground-truth notes.
"""
