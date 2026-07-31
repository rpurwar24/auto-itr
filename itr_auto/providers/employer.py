"""Employer documents - salary (Form 16 + computation) and RSU/ESPP vest statements.

Backed by parsers/itcs.py + parsers/perquisite.py. Employer-specific identifiers (TAN, name,
salary component labels) live in the workspace profile (config/profile.json), not here.
"""
from itr_auto.providers.base import Provider, DocSlot


def _slots(fy):
    return [
        DocSlot(id="adobe_form16", label="Form 16",
                desc="Annual TDS certificate (Part A + Part B + 12BA/12BAA) from your employer.",
                dest="adobe/{fy}", filename="form16.pdf", multiple=False, required=True, accept=".pdf"),
        DocSlot(id="adobe_itcs", label="Salary computation (ITCS)",
                desc="Employer's Income Tax Computation Statement - the component-wise salary breakup.",
                dest="adobe/{fy}", filename="itcs.pdf", multiple=False, required=True, accept=".pdf"),
        DocSlot(id="adobe_esop", label="ESOP / RSU vest statements",
                desc="Perquisite/ESOP statements (one per FY, cumulative). Used for RSU/ESPP cost "
                     "basis + Schedule FA. You can select several at once.",
                dest="adobe/esop", filename=None, multiple=True, required=True, accept=".html,.htm"),
    ]


PROVIDER = Provider(id="employer", name="Employer", category="employer", order=20, slots=_slots)
