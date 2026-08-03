"""Estimate the pace model's observation noise from data, instead of guessing.

`pace_model.DEFAULTS["base_noise"]` says how representative a practice
session is of the real thing, over and above lap-time scatter. Those numbers
were hand-set and a grid search over them was inconclusive (the long-run
constants are literally unidentifiable on 2024 — see the note in pace_model).
This script estimates them a different way, from an identity rather than a
search, so the answer does not depend on a scoring loop at all.

The identity
------------
Write a session measurement as  m = θ + ε,  where θ is the team's true pace
for the weekend and ε is everything that makes practice not the race (fuel,
engine mode, programme, plus fit noise). The outcome is r = θ + η. Regress
the outcome on the measurement across many team-events:

    slope = cov(r, m) / var(m) = var(θ) / (var(θ) + var(ε))

Noise in the OUTCOME (η) does not bias that slope — only noise in the
measurement does. So the slope IS the attenuation factor, and

    var(ε) = (1 − slope) · var(m)
    base_noise² = var(ε) − mean(se²)          (se is already in the model)

That is the whole method: measure how much practice shrinks toward the
outcome, and back out how noisy it must have been.

Reading the output
------------------
`implied` below the current value means the model TRUSTS that session more
than the data supports, and its updates will overshoot. Everything is
reported per (kind, session) with the sample size, and pre-2026 is kept
separate from 2026 — 2026 is the never-tuned holdout, and a constant fitted
on it would stop being one.

    python scripts/calibrate_pace_noise.py
    python scripts/calibrate_pace_noise.py --min-n 60
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
from scipy import stats

from f1lib.config import apply_pace_legacy_columns
from f1lib.pace_features import canon, event_measurements
from f1lib.pace_model import DEFAULTS, era_of

PACE_CSV = "data/team_pace_by_event.csv"

# measurement kind → the column of team_pace_by_event.csv it is predicting
TARGET = {"onelap": "onelap_speed_pct", "longrun": "race_pace_pct"}


def collect() -> pd.DataFrame:
    """One row per (season, event, session, kind, team): the measurement, its
    standard error, and the outcome it was trying to predict — both centred
    on the teams common to that measurement set, exactly as the model's
    update re-anchors them."""
    pace = apply_pace_legacy_columns(pd.read_csv(PACE_CSV))
    pace["team"] = pace["team"].map(canon)
    rows = []
    events = pace[["season", "event"]].drop_duplicates().itertuples(index=False)
    for season, event in events:
        try:
            meas, _ = event_measurements(season, event)
        except Exception as exc:
            print(f"  [{season} {event}] measurements failed: {exc}")
            continue
        if meas is None or meas.empty:
            continue
        ev = pace[(pace["season"] == season) & (pace["event"] == event)]
        for (session, kind), mset in meas.groupby(["session", "kind"]):
            tgt = ev.set_index("team")[TARGET[kind]].dropna()
            m = mset.set_index("team")
            common = sorted(set(m.index) & set(tgt.index))
            if len(common) < 6:
                continue
            gap = m.loc[common, "gap_pct"]
            out = tgt.loc[common]
            rows.append(pd.DataFrame({
                "season": season, "event": event, "session": session,
                "kind": kind, "team": common,
                "m": (gap - gap.mean()).values,
                "se": m.loc[common, "se_pct"].values,
                "r": (out - out.mean()).values,
            }))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def implied_noise(sub: pd.DataFrame) -> dict:
    """Back out base_noise for one (kind, session) block."""
    slope, _icept, r, p, se_slope = stats.linregress(sub["m"], sub["r"])
    var_m = float(np.var(sub["m"], ddof=1))
    mean_se2 = float(np.mean(sub["se"] ** 2))
    # slope is clipped into (0,1): a slope at or above 1 means no detectable
    # attenuation (noise ≈ 0), below 0 means no signal at all (noise huge).
    s = float(np.clip(slope, 1e-3, 0.999))
    var_eps = (1.0 - s) * var_m
    noise2 = var_eps - mean_se2
    return {
        "n": len(sub), "slope": slope, "slope_se": se_slope, "r": r, "p": p,
        "sd_m": float(np.sqrt(var_m)), "mean_se": float(np.sqrt(mean_se2)),
        # A non-positive implied variance means the fit SE alone already
        # accounts for the whole spread: there is nothing left to attribute to
        # base_noise, and the block says nothing about what it should be. That
        # is "not identified", NOT "the noise is zero" — the difference
        # matters, because reading it as zero would argue for trusting the
        # session completely.
        "implied": float(np.sqrt(noise2)) if noise2 > 0 else float("nan"),
        "identified": bool(noise2 > 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=40,
                    help="skip blocks with fewer team-observations")
    args = ap.parse_args()

    d = collect()
    if d.empty:
        print("No measurements collected.")
        return 1
    d["era"] = d["season"].map(era_of)
    d["holdout"] = np.where(d["season"] >= 2026, "2026 (holdout)", "pre-2026")
    print(f"\n{len(d)} team-observations across "
          f"{d.groupby(['season', 'event']).ngroups} events\n")

    base = DEFAULTS["base_noise"]
    default = DEFAULTS["default_base_noise"]
    hdr = (f"{'kind':8s} {'session':18s} {'split':14s} {'n':>4s} "
           f"{'slope':>13s} {'sd(m)':>6s} {'se':>5s} {'implied':>8s} "
           f"{'current':>8s}  verdict")
    print(hdr)
    print("-" * len(hdr))
    for (kind, session), block in d.groupby(["kind", "session"]):
        for split in ("pre-2026", "2026 (holdout)"):
            sub = block[block["holdout"] == split]
            if len(sub) < args.min_n:
                continue
            s = implied_noise(sub)
            cur = base.get((kind, session), default)
            if not s["identified"]:
                verdict, shown = "SE-dominated — not identified", "     n/a"
            else:
                ratio = s["implied"] / cur if cur else np.inf
                verdict = ("model trusts it too much" if ratio > 1.25 else
                           "model too sceptical" if ratio < 0.8 else
                           "about right")
                shown = f"{s['implied']:8.3f}"
            print(f"{kind:8s} {session:18s} {split:14s} {s['n']:4d} "
                  f"{s['slope']:6.3f}±{s['slope_se']:5.3f} {s['sd_m']:6.3f} "
                  f"{s['mean_se']:5.3f} {shown} {cur:8.2f}  {verdict}")

    print("\nslope = var(true) / var(measured): 1.0 would mean practice reads "
          "race pace exactly.\nimplied = the base_noise that slope implies, "
          "after removing the fit SE the model already carries.")
    print("\nPre-2026 is the estimation sample; the 2026 column is reported "
          "for information only —\nfitting a constant on the holdout would "
          "stop it being one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
