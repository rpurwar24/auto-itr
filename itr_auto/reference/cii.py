"""Cost Inflation Index (CII) - public data notified by the Income Tax Department.

Used for indexed LTCG cost on transfers BEFORE 23-Jul-2024 (Finance Act 2024 removed indexation
for transfers on/after that date). Keyed by financial year in the "YYYY-YYYY" form that
compute.capital_gains.cii_fy() produces. This is a static public table, so the pipeline no longer
needs the taxpayer's .numbers oracle just to look up an index.
"""
from __future__ import annotations

CII: dict[str, int] = {
    "2001-2002": 100, "2002-2003": 105, "2003-2004": 109, "2004-2005": 113,
    "2005-2006": 117, "2006-2007": 122, "2007-2008": 129, "2008-2009": 137,
    "2009-2010": 148, "2010-2011": 167, "2011-2012": 184, "2012-2013": 200,
    "2013-2014": 220, "2014-2015": 240, "2015-2016": 254, "2016-2017": 264,
    "2017-2018": 272, "2018-2019": 280, "2019-2020": 289, "2020-2021": 301,
    "2021-2022": 317, "2022-2023": 331, "2023-2024": 348, "2024-2025": 363,
    "2025-2026": 376,
}
