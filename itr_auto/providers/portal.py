"""e-Filing portal prefill - the identity/salary/TDS base the generator builds on."""
from itr_auto.providers.base import Provider, DocSlot


def _slots(fy):
    return [DocSlot(
        id="portal_base", label="ITR-2 template JSON",
        desc="An ITR-2 JSON used as the identity/personal template. Easiest: open the ITD offline "
             "Utility, import your prefill, and Export the ITR-2 JSON (or use last year's ITR-2 "
             "return JSON). NOTE: the portal's raw 'Download Prefill' camelCase file is NOT this "
             "format and won't work yet.",
        dest="portal/{fy}", filename="base.json", multiple=False, required=True, accept=".json")]


PROVIDER = Provider(id="portal", name="Portal", category="portal", order=10, slots=_slots)
