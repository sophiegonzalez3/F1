"""Compare race control's DNF attribution with the press, retirement by
retirement — the audit of the rule base in f1lib/incidents.py.

Race control explains a retirement as a collision when a logged contact sits
within a few laps of the stop. That is an INFERENCE, and it can be wrong (a
no-action brush three laps before a battery failure; a contact CAUSED by a
gearbox failure). data/dnf_press_review.csv holds an independent press verdict
for those retirements; this lists every one where the two disagree, on the
family or on the other car. It changes nothing: a disagreement is settled by
hand, with `overrides_register` in data/dnf_causes.csv when the press (or the
stewards' own decision) shows the inference was wrong.

Usage
-----
    python scripts/compare_press_register.py              # every season
    python scripts/compare_press_register.py --season 2026
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
from pathlib import Path

import pandas as pd

from f1lib.dnf_causes import resolve_cause, normalise_family

REVIEW = Path("data/dnf_press_review.csv")


def compare(season: int | None = None) -> pd.DataFrame:
    if not REVIEW.exists():
        return pd.DataFrame()
    p = pd.read_csv(REVIEW, dtype=str, keep_default_na=False)
    if season:
        p = p[p["season"] == str(season)]
    out = []
    for r in p.itertuples():
        got = resolve_cause(int(r.season), r.event, r.driver,
                            float(r.laps) if r.laps else None)
        fam_p = normalise_family(r.press_family)
        out.append({
            "season": r.season, "round": r.round, "event": r.event,
            "driver": r.driver, "dashboard": got["cause_family"] or "—",
            "dashboard_source": got["cause_source"] or "—",
            "press": fam_p or "—",
            "family_agrees": got["cause_family"] == fam_p,
            "other_car_agrees": (not r.press_counterparty
                                 or not got.get("counterparty")
                                 or got["counterparty"] == r.press_counterparty),
            "press_ruling": r.press_ruling,
        })
    return pd.DataFrame(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int)
    a = ap.parse_args()
    d = compare(a.season)
    if d.empty:
        print(f"No press review rows in {REVIEW}.")
        return 0
    bad = d[~d["family_agrees"] | ~d["other_car_agrees"]]
    print(f"{len(d)} retirement(s) press-reviewed · {int(d['family_agrees'].sum())} "
          f"agree on the family · {len(bad)} to look at\n")
    if not bad.empty:
        print(bad.drop(columns=["family_agrees"]).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
