"""Validate the race-result forecast's pace+grid+passability blend.

Two questions, kept separate:

  1. Is the COMBINATION MODEL sound? Using ACTUAL race pace and ACTUAL grid
     (so pace-prediction error is out of the picture), does blending them by
     circuit passability reconstruct the finishing order better than grid
     alone or pace alone? This tests race_forecast's core mechanism.

  2. End-to-end: does the full forecast (PREDICTED pace, as-of leak-free)
     rank the actual finishers respectably?

Run once the model + tables exist:
    python backtest_race_forecast.py
"""
from __future__ import annotations

import warnings
import logging

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from race_forecast import RaceForecaster
from driver_ratings import DriverRatings


def combination_test() -> None:
    rf = RaceForecaster()
    dr = DriverRatings()
    res = rf._results.copy()
    res["fin"] = res["Position"]
    dp = dr.pace[dr.pace["kind"] == "race"]
    rows = []
    for (season, event), g in dp.groupby(["season", "event"]):
        prank = g.set_index("driver")["gap_pct"].rank()   # 1=fastest pace
        rr = res[(res["season"] == season) & (res["event_name"] == event)] \
            .dropna(subset=["GridPosition", "fin"]).copy()
        rr["driver"] = rr["Abbreviation"]
        rr = rr[rr["driver"].isin(prank.index)]
        if len(rr) < 8:
            continue
        pull = rf.passability(event)
        grid = rr.set_index("driver")["GridPosition"]
        finish = rr.set_index("driver")["fin"]
        pr = prank.reindex(grid.index)
        blend = grid + pull * (pr - grid)
        a = finish.values
        rows.append({
            "rho_grid": spearmanr(grid.values, a).correlation,
            "rho_pace": spearmanr(pr.values, a).correlation,
            "rho_blend": spearmanr(blend.values, a).correlation})
    R = pd.DataFrame(rows).dropna()
    print(f"\n== Combination model ({len(R)} races, actual pace + actual grid) ==")
    print(f"  grid-only   Spearman vs finish: {R['rho_grid'].mean():.3f}")
    print(f"  pace-only   Spearman vs finish: {R['rho_pace'].mean():.3f}")
    print(f"  BLEND       Spearman vs finish: {R['rho_blend'].mean():.3f}")
    both = ((R["rho_blend"] >= R["rho_grid"] - 1e-9)
            & (R["rho_blend"] >= R["rho_pace"] - 1e-9)).sum()
    print(f"  blend >= both baselines on {both}/{len(R)} races")


def endtoend_test() -> None:
    """Full forecast with predicted pace + actual grid, leak-free as-of."""
    from pace_model import PaceModel
    from pace_features import event_measurements
    m = PaceModel()
    rf = RaceForecaster()
    dr = DriverRatings()
    res = rf._results.copy()
    res["fin"] = res["Position"]
    rows = []
    for (season, event), g in dr.pace[dr.pace["kind"] == "race"] \
            .groupby(["season", "event"]):
        rnd = m.round_of(season, event)
        if rnd is None:
            continue
        try:
            meas, _ = event_measurements(season, event)
            if meas is None or meas.empty:
                continue
            stages = m.predict_weekend(season, event, measurements=meas,
                                       round_=rnd)
        except Exception:
            continue
        final = list(stages.values())[-1]
        roster = dr.roster(season, event)
        race_pred = m.driver_predictions(final, roster, "longrun",
                                         as_of=(season, rnd))
        if race_pred.empty:
            continue
        rr = res[(res["season"] == season) & (res["event_name"] == event)] \
            .dropna(subset=["GridPosition", "fin"]).copy()
        rr["driver"] = rr["Abbreviation"]
        grid = rr.set_index("driver")["GridPosition"].astype(int).to_dict()
        fc = rf.forecast(race_pred, event=event, grid=grid)
        merged = fc.merge(rr[["driver", "fin"]], on="driver")
        if len(merged) < 8:
            continue
        rows.append({"rho": spearmanr(merged["e_finish"],
                                      merged["fin"]).correlation,
                     "n": len(merged)})
    R = pd.DataFrame(rows).dropna()
    if not R.empty:
        print(f"\n== End-to-end ({len(R)} races, predicted pace + actual grid) ==")
        print(f"  forecast E[finish] Spearman vs actual finish: "
              f"{R['rho'].mean():.3f}")


if __name__ == "__main__":
    combination_test()
    endtoend_test()
