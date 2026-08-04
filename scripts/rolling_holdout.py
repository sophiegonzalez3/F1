"""Rolling-holdout evaluation: would this model have worked in 2023? In 2024?

Every improvement in this project has been validated on a single holdout
season — 2026. That is enough to avoid tuning ON the holdout, but it is not
enough to tell a robust improvement from a coincidence of one season. A
change that helps in 2026 and hurts in 2024 and 2025 looks identical, in a
single-season report, to one that helps everywhere.

This harness scores the model one holdout season at a time, so a variant has
to earn its keep on several independent years rather than one. It is
deliberately a comparison tool, not a tuner: it reports per-year numbers and
refuses to pick a winner, because picking the variant that scores best on
the average of all years is just tuning on all of them at once.

What "holdout" does and does not mean here
------------------------------------------
The DATA is already out of sample by construction: the prior only ever reads
strictly-earlier rounds, so scoring 2024 never sees 2024's later rounds or
anything after. What is NOT out of sample is the CONSTANTS — base_noise and
the prior parameters are global and were calibrated on pre-2026 pooled data.
So a per-year score answers "how would the CURRENT constants have done in
year Y", which is the robustness question, not "what would a model trained
only up to Y have done". The distinction matters and is the reason this
script does not claim to be a full walk-forward retraining.

One structural limit, worth stating rather than discovering later: 2023,
2024 and 2025 all sit inside the ground-effect era, so they test robustness
WITHIN an era. Only 2026 is an era opening. Anything specific to a
regulation break is still validated on a single case, and no amount of
rolling can fix that — there have only been two breaks in the archive.

Usage
-----
    python scripts/rolling_holdout.py
    python scripts/rolling_holdout.py --seasons 2024 2025 2026
    python scripts/rolling_holdout.py --variant half_life_rounds=6
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import importlib.util
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from f1lib.pace_model import PaceModel, era_of

_spec = importlib.util.spec_from_file_location(
    "backtest_pace_model", Path(__file__).with_name("backtest_pace_model.py"))
_bt = importlib.util.module_from_spec(_spec)
_sys.modules["backtest_pace_model"] = _bt
_spec.loader.exec_module(_bt)

# The stage a weekend actually ends on, i.e. the number the dashboard shows
# once everything available has been ingested. Scoring the whole stage ladder
# per year buries the comparison in rows nobody reads.
_FINAL_STAGES = ("after Quali", "after Sprint", "after FP3", "after FP2",
                 "after FP1", "prior")


def _final_read(bt: pd.DataFrame) -> pd.DataFrame:
    """One row per (season, event, kind): the last stage available."""
    if bt.empty:
        return bt
    rank = {s: i for i, s in enumerate(_FINAL_STAGES)}
    b = bt[bt["stage"].isin(rank)].copy()
    b["_r"] = b["stage"].map(rank)
    return (b.sort_values("_r").groupby(["season", "event", "kind"], as_index=False)
            .first().drop(columns="_r"))


def score_year(season: int, overrides: dict) -> pd.DataFrame:
    model = PaceModel(**overrides)
    bt = _bt.backtest(model, [season], verbose=False)
    if bt.empty:
        return bt
    fin = _final_read(bt)
    pri = bt[bt["stage"] == "prior"]
    rows = []
    for kind in ("onelap", "longrun"):
        f = fin[fin["kind"] == kind]
        p = pri[pri["kind"] == kind]
        if f.empty:
            continue
        rows.append({
            "season": season, "era": era_of(season), "kind": kind,
            "n_events": len(f),
            "prior_mae": p["mae"].mean() if not p.empty else np.nan,
            "final_mae": f["mae"].mean(),
            "prior_rho": p["rho"].mean() if not p.empty else np.nan,
            "final_rho": f["rho"].mean(),
        })
    return pd.DataFrame(rows)


def run(seasons: list[int], variants: dict[str, dict]) -> pd.DataFrame:
    out = []
    for name, ov in variants.items():
        for season in seasons:
            df = score_year(season, ov)
            if df.empty:
                continue
            df.insert(0, "variant", name)
            out.append(df)
            for _, r in df.iterrows():
                print(f"  {name:16s} {season}  {r['kind']:8s} "
                      f"prior {r['prior_mae']:.3f} -> final {r['final_mae']:.3f}   "
                      f"rho {r['final_rho']:.3f}   n={int(r['n_events'])}",
                      flush=True)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def report(res: pd.DataFrame) -> None:
    if res.empty:
        print("Nothing scored.")
        return
    base = res[res["variant"] == "baseline"]
    others = sorted(set(res["variant"]) - {"baseline"})
    for kind in ("onelap", "longrun"):
        b = base[base["kind"] == kind].set_index("season")
        if b.empty:
            continue
        print(f"\n=== {kind} — final read, MAE by holdout season ===")
        hdr = f"{'variant':16s}" + "".join(f"{s:>9}" for s in b.index) + "   wins"
        print(hdr)
        print("-" * len(hdr))
        print(f"{'baseline':16s}" + "".join(f"{v:9.3f}" for v in b["final_mae"]))
        for name in others:
            o = res[(res["variant"] == name) & (res["kind"] == kind)] \
                .set_index("season").reindex(b.index)
            delta = o["final_mae"] - b["final_mae"]
            wins = int((delta < 0).sum())
            print(f"{name:16s}" + "".join(f"{v:+9.3f}" for v in delta)
                  + f"   {wins}/{delta.notna().sum()}")
        print("  (variant rows are DELTA vs baseline; negative = better)")
    print("\nA variant is worth keeping when it wins on MOST years, not when "
          "it wins on average —\nan average is dominated by whichever season "
          "happens to be hardest.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int,
                    default=[2023, 2024, 2025, 2026])
    ap.add_argument("--variant", nargs="*", default=[], metavar="K=V",
                    help="model override(s), e.g. half_life_rounds=6. Each "
                         "flag adds one variant scored against the baseline.")
    ap.add_argument("--out", default="data/rolling_holdout.csv")
    args = ap.parse_args()

    variants: dict[str, dict] = {"baseline": {}}
    for spec in args.variant:
        k, _, v = spec.partition("=")
        try:
            val = float(v)
        except ValueError:
            val = v
        variants[spec] = {k: val}

    print(f"Scoring {len(variants)} variant(s) over {args.seasons}\n")
    res = run(args.seasons, variants)
    report(res)
    if not res.empty:
        res.to_csv(args.out, index=False)
        print(f"\nWrote {len(res)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
