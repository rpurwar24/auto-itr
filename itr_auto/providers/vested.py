"""Vested / DriveWealth - US ETF/stock holdings (Schedule FA) + dividends + FTC (Form 67)."""
from itr_auto.providers.base import Provider, DocSlot


def _slots(fy):
    return [DocSlot(
        id="vested", label="Vested / DriveWealth bundle",
        desc="Vested's ITR helper workbooks (Schedule FA / FSI / Form 67 / summary). "
             "Add all the files from the bundle.",
        dest="vested/{fy}", filename=None, multiple=True, required=False, accept=".xlsx")]


PROVIDER = Provider(id="vested", name="Vested", category="custodian", order=60, slots=_slots)
