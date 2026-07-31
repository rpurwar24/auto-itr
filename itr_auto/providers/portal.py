"""e-Filing portal prefill - the identity/salary/TDS base the generator builds on."""
from itr_auto.providers.base import Provider, DocSlot


def _slots(fy):
    return [DocSlot(
        id="portal_base", label="Prefill JSON",
        desc="Your prefilled data - it seeds identity, address and bank details. Use the portal's "
             "'Download Prefill' JSON (Portal > e-File > Income Tax Return > Download Prefill), or "
             "an ITD offline-Utility ITR-2 export / a prior ITR-2 return. All work.",
        dest="portal/{fy}", filename="base.json", multiple=False, required=True, accept=".json")]


PROVIDER = Provider(id="portal", name="Portal", category="portal", order=10, slots=_slots)
