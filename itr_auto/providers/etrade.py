"""E*TRADE - RSU/ESPP sale data (Gain & Loss Expanded) + optional trade confirmations."""
from itr_auto.providers.base import Provider, DocSlot


def _slots(fy):
    return [
        DocSlot(id="etrade_gl", label="Gain & Loss (Expanded)",
                desc="E*TRADE 'G&L Expanded' xlsx (per US calendar year) - the specific-ID sale "
                     "data for capital gains. Add one per calendar year covering the FY.",
                dest="etrade/gains_losses", filename=None, multiple=True, required=True, accept=".xlsx"),
        DocSlot(id="etrade_trades", label="Trade confirmations",
                desc="Trade confirmation PDFs (optional cross-check; G&L is preferred). Multiple allowed.",
                dest="etrade/trades", filename=None, multiple=True, required=False, accept=".pdf"),
    ]


PROVIDER = Provider(id="etrade", name="E*TRADE", category="broker", order=50, slots=_slots)
