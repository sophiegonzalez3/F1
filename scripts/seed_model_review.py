"""Seed the hand-curated post-race review with the rows that need writing.

The prediction ledger can say the model was wrong. It structurally cannot say
WHY — only somebody who watched the race knows a car picked up floor damage on
lap 3, or served a penalty and pitted out of sequence. Those causes are
precisely the things the pace model declines to model (strategy, incidents,
damage, weather), so this file is not patching a hidden gap; it documents the
gap the model already admits to.

What this script does is remove the tedious half of that job. It works out
which drivers finished OUTSIDE their own +/-1sd band, fills in every number
automatically, and appends a skeleton row per driver with two fields left
blank for a human: `category` and `note`. Typically three to six rows a race.

    python scripts/seed_model_review.py --season 2026 --event "Belgian Grand Prix"
    python scripts/seed_model_review.py --latest      # newest event in the pace table

Then open data/model_review.csv and fill in the blanks.

WHY `category` MATTERS more than `note`: free text gives a readable race diary
and nothing else. A category drawn from a fixed vocabulary turns a season of
anecdotes into a distribution, which answers the question that actually
directs the roadmap — "what share of our misses are unmodelled incidents
versus the model genuinely being wrong?" If most misses are `strategy`, the
next thing to build is a strategy model; if most are `model_miss`, the pace
model itself needs the work.

Nothing here writes `category` or `note`. A machine guessing why a car was
slow would be inventing race history, and this file is only worth having if
every word in it is something a person actually observed.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

OUT = Path("data/model_review.csv")

COLUMNS = ["season", "round", "event", "driver", "team", "kind",
           "predicted", "actual", "miss", "sd", "category", "note"]

# Fixed vocabulary. Keep it SHORT — a long list gets used inconsistently and
# stops aggregating, which defeats the point.
CATEGORIES = [
    "damage",       # contact or debris cost lasting pace
    "strategy",     # tyre/pit calls the model does not simulate
    "traffic",      # stuck behind a slower car, never showed true pace
    "penalty",      # time penalty or serving cost
    "weather",      # conditions changed within or between sessions
    "reliability",  # mechanical trouble short of a retirement
    "driver_error", # spin, lock-up, off
    "setup",        # team changed the car between the read and the session
    "model_miss",   # none of the above — the model was simply wrong
]


def _driver_actuals(season: int, event: str) -> dict[str, pd.Series]:
    """Per-driver outcome for both kinds, mean-centred, from the pace table."""
    p = Path("data/driver_pace_by_event.csv")
    if not p.exists():
        return {}
    d = pd.read_csv(p)
    d = d[(d["season"] == season) & (d["event"] == event)].dropna(
        subset=["gap_pct"])
    out = {}
    for kind, tgt in (("onelap", "quali"), ("longrun", "race")):
        s = d[d["kind"] == tgt].set_index("driver")["gap_pct"]
        if len(s) >= 4:
            out[kind] = s - s.mean()
    return out


def seed(season: int, event: str) -> pd.DataFrame:
    from f1lib.pace_model import PaceModel
    from f1lib.pace_features import event_measurements
    from f1lib.driver_ratings import DriverRatings

    model = PaceModel()
    round_ = model.round_of(season, event) or model.next_round_of(season)
    meas, _ = event_measurements(season, event)
    stages = model.predict_weekend(season, event,
                                   measurements=meas if meas is not None
                                   and not meas.empty else None,
                                   round_=round_)
    final = stages[list(stages)[-1]]
    dr = DriverRatings()
    roster = dr.roster(season, event)
    actuals = _driver_actuals(season, event)
    rows = []
    for kind, act in actuals.items():
        pred = model.driver_predictions(final, roster, kind,
                                        as_of=(season, round_))
        if pred.empty:
            continue
        pred = pred.set_index("driver")
        common = [d for d in pred.index if d in act.index]
        if len(common) < 4:
            continue
        pv = pred.loc[common, "mean"] - pred.loc[common, "mean"].mean()
        av = act[common] - act[common].mean()
        for d in common:
            miss = float(av[d] - pv[d])
            sd = float(pred.loc[d, "sd"])
            if abs(miss) <= sd:              # inside its own band: no review
                continue
            rows.append({
                "season": season, "round": round_, "event": event,
                "driver": d, "team": pred.loc[d, "team"], "kind": kind,
                "predicted": round(float(pv[d]), 3),
                "actual": round(float(av[d]), 3),
                "miss": round(miss, 3), "sd": round(sd, 3),
                "category": "", "note": "",
            })
    return pd.DataFrame(rows, columns=COLUMNS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--event")
    ap.add_argument("--latest", action="store_true",
                    help="use the newest event in the pace table")
    args = ap.parse_args()

    if args.latest or not (args.season and args.event):
        from f1lib.pace_model import PaceModel
        p = PaceModel().pace
        last = p.sort_values(["season", "round"]).iloc[-1]
        season, event = int(last["season"]), str(last["event"])
        print(f"[latest] {season} {event}")
    else:
        season, event = args.season, args.event

    new = seed(season, event)
    if new.empty:
        print("No driver fell outside their error bar — nothing to review. "
              "(That is a good weekend, not a bug.)")
        return 0

    if OUT.exists():
        old = pd.read_csv(OUT)
        # never clobber a note somebody already wrote
        key = ["season", "event", "driver", "kind"]
        merged = old.merge(new[key], on=key, how="right", indicator=True)
        already = int((merged["_merge"] == "both").sum())
        new = new.merge(old[key].assign(_seen=1), on=key, how="left")
        new = new[new["_seen"].isna()].drop(columns=["_seen"])
        if already:
            print(f"{already} row(s) already reviewed — left untouched")
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    print(f"\nAdded {len(new)} row(s) awaiting a note -> {OUT}")
    if not new.empty:
        print(new[["driver", "kind", "predicted", "actual", "miss",
                   "sd"]].to_string(index=False))
    print(f"\nFill in `category` (one of: {', '.join(CATEGORIES)}) and `note`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
