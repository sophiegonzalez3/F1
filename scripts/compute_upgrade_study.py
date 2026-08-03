"""Estimate the upgrade event study -> data/upgrade_study.csv.

Fits the panel specifications in f1lib/upgrade_study.py (dose-response and
event study, team + round fixed effects, wild cluster bootstrap inference)
for every season that has both a pace table and declared upgrades, plus the
two robustness checks that decide whether the headline is believable:

  leave-one-out   refit dropping each team in turn. With eleven clusters a
                  single team can carry a coefficient; if the sign survives
                  every drop, it does not.
  placebo         reshuffle each team's upgrade timing within its own season
                  and refit, many times. The real coefficient has to sit
                  outside that null distribution to mean anything. Note the
                  null is NOT centred on zero: cumulative components rise
                  over a season no matter how they are shuffled, so the
                  placebo mean is the part of the effect that is just "later
                  in the season", and the real estimate has to beat THAT.

Written as one long table so the card renders without refitting.

    python scripts/compute_upgrade_study.py
    python scripts/compute_upgrade_study.py --season 2026 --placebo 500
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from f1lib.upgrade_study import (
    MAJOR_ITEMS, OUTCOMES, STUDY_PATH, build_panel, dose_response,
    event_study, pretrend_ok,
)


def robustness(panel: pd.DataFrame, kind: str, n_placebo: int,
               seed: int = 5) -> list[dict]:
    rows = []
    base = float(dose_response(panel, kind, boot=False).iloc[0]["coef"])
    loo = []
    for t in sorted(panel["team"].unique()):
        sub = panel[panel["team"] != t]
        if sub["team"].nunique() < 4:
            continue
        c = float(dose_response(sub, kind, boot=False).iloc[0]["coef"])
        loo.append(c)
        rows.append({"spec": "loo", "kind": kind, "term": f"drop {t}",
                     "coef": c})
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(n_placebo):
        q = panel.copy()
        q["dev_items"] = q.groupby("team")["dev_items"].transform(
            lambda s: rng.permutation(s.values))
        q = q.sort_values(["team", "round"])
        q["cum_items"] = q.groupby("team")["dev_items"].cumsum()
        null.append(float(dose_response(q, kind, boot=False).iloc[0]["coef"]))
    null = np.array(null)
    rows.append({
        "spec": "placebo", "kind": kind, "term": "null",
        "coef": float(null.mean()), "se_cluster": float(null.std()),
        "p_wild": float((null <= base).mean() if base < 0
                        else (null >= base).mean()),
        "n": n_placebo,
    })
    rows.append({
        "spec": "loo_summary", "kind": kind, "term": "range",
        "coef": base, "lo": float(min(loo)) if loo else np.nan,
        "hi": float(max(loo)) if loo else np.nan,
        "same_sign": bool(loo and all(np.sign(c) == np.sign(base)
                                      for c in loo)),
    })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--placebo", type=int, default=200)
    args = ap.parse_args()

    pace = pd.read_csv("data/team_pace_by_event.csv")
    up = pd.read_csv("data/upgrades.csv", encoding="utf-8-sig")
    seasons = ([args.season] if args.season else
               sorted(set(pace["season"]) & set(up["season"])))
    if not seasons:
        print("No season has both a pace table and declared upgrades.")
        return 1

    out = []
    for season in seasons:
        panel = build_panel(int(season))
        if panel.empty or panel["team"].nunique() < 6:
            print(f"[{season}] panel too thin — skipped")
            continue
        n_major = int(panel["major"].sum())
        print(f"[{season}] {len(panel)} team-rounds, {panel['team'].nunique()} "
              f"teams, {n_major} major packages (>= {MAJOR_ITEMS} items)")
        for kind in OUTCOMES:
            d = dose_response(panel, kind)
            r = d.iloc[0]
            print(f"   {kind:8s} dose {r['coef']:+.4f} pp/item "
                  f"(p_wild {r['p_wild']:.3f}, n={d.attrs['n']})")
            out.append({"season": season, "spec": "dose", "kind": kind,
                        "term": "cum_items", "coef": r["coef"],
                        "se_cluster": r["se_cluster"], "p_wild": r["p_wild"],
                        "n": d.attrs["n"], "n_teams": d.attrs["n_teams"]})
            ev = event_study(panel, kind)
            if not ev.empty:
                clean = pretrend_ok(ev)
                print(f"   {kind:8s} event study n={ev.attrs['n']}, "
                      f"pre-trend {'clean' if clean else 'FAILED'}")
                for _, e in ev.iterrows():
                    out.append({"season": season, "spec": "event",
                                "kind": kind, "term": e["term"],
                                "coef": e["coef"], "se_cluster": e["se_cluster"],
                                "p_wild": e["p_wild"], "n": ev.attrs["n"],
                                "pretrend_clean": clean})
            for row in robustness(panel, kind, args.placebo):
                out.append({"season": season, **row})

    if not out:
        print("Nothing estimated.")
        return 1
    df = pd.DataFrame(out)
    df.to_csv(STUDY_PATH, index=False)
    print(f"\nWrote {len(df)} rows -> {STUDY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
