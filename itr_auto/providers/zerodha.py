"""Zerodha - domestic equity/MF capital-gains (Tax P&L: STCG 111A / LTCG 112A split)."""
from itr_auto.providers.base import Provider, DocSlot


def _slots(fy):
    return [DocSlot(
        id="zerodha_taxpnl", label="Tax P&L",
        desc="Zerodha Console > Reports > Tax P&L (has the STCG/LTCG split for domestic MF/equity).",
        dest="zerodha/{fy}", filename=None, multiple=True, required=False, accept=".xlsx")]


PROVIDER = Provider(id="zerodha", name="Zerodha", category="broker", order=70, slots=_slots)
