"""e-Filing portal prefill - the identity/salary/TDS base the generator builds on."""
from itr_auto.providers.base import Provider, DocSlot


def _slots(fy):
    return [DocSlot(
        id="portal_base", label="Prefill JSON",
        desc="e-Filing portal prefill (identity, salary, TDS/TCS). "
             "Portal > e-File > Income Tax Return > Download Prefill JSON.",
        dest="portal/{fy}", filename="base.json", multiple=False, required=True, accept=".json")]


PROVIDER = Provider(id="portal", name="Portal", category="portal", order=10, slots=_slots)
