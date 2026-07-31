"""Income Tax Department AIS/TIS - authoritative TDS/TCS, interest, dividend aggregates."""
from itr_auto.providers.base import Provider, DocSlot


def _slots(fy):
    return [
        DocSlot(id="ais_ais", label="AIS",
                desc="Annual Information Statement PDF (Compliance portal). "
                     "Password = PAN(lower)+DOB(ddmmyyyy).",
                dest="ais/{fy}", filename="ais.pdf", multiple=False, required=True, accept=".pdf"),
        DocSlot(id="ais_tis", label="TIS",
                desc="Taxpayer Information Summary PDF (authoritative dividend aggregate).",
                dest="ais/{fy}", filename="tis.pdf", multiple=False, required=False, accept=".pdf"),
    ]


PROVIDER = Provider(id="ais", name="Income Tax Dept", category="tax-authority", order=30, slots=_slots)
