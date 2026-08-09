"""Score the race-OUTCOME forecast, and compare it with the betting market.

WHY THIS FILE CHANGED SHAPE
---------------------------
`race_forecast.py` emits p_win / p_podium / p_points / e_finish / p_dnf and,
until now, none of them had ever been scored. This script measured two
Spearman correlations — useful, but a rank correlation says nothing about
whether a stated 30% happens 30% of the time. `backtest_pace_model.csv` scores
the PACE layer eight ways; the outcome layer, which is the thing actually
wanted, had no track record at all.

So the two rank tests are kept (they answer "is the blend sound?") and a
proper probabilistic scorecard is added underneath them.

WHAT IS MEASURED
----------------
  Brier + log loss on p_win, p_podium, p_points, p_dnf
  MAE + RMSE on e_finish
  reliability bins (does a stated 30% happen 30% of the time?)

against three references, in increasing order of difficulty:

  climatology  the field base rate — 1/n win, 3/n podium. Beating this is
               the minimum bar; a model that cannot is worse than knowing
               only how many cars started.
  grid         P(outcome | grid slot), fitted ONLY on races strictly before
               the one being scored. Much of a race result is where you
               started, so this is the honest baseline — and an expanding
               window keeps it leak-free the same way the pace model's
               `as_of` does.
  market       what the money said just before lights out, de-vigged.
               Available for 2024-26 only. This is a HARD reference: it
               knows the grid, the weather and the paddock news, so losing
               to it is expected. Systematic DISAGREEMENT is the signal —
               that is what says where the outcome layer is wrong.

LEAKAGE
-------
Pace comes from `as_of=(season, round)`, so no future weekend informs a
prediction. The grid baseline uses prior races only. The market is scored
alongside the model and is NEVER an input to it — see tests/test_odds.py,
which enforces that structurally.

Usage
-----
    .venv/Scripts/python scripts/backtest_race_forecast.py
    .venv/Scripts/python scripts/backtest_race_forecast.py --seasons 2024 2025 2026
    .venv/Scripts/python scripts/backtest_race_forecast.py --rank-tests-only
    .venv/Scripts/python scripts/backtest_race_forecast.py --report   # re-score
                                            # the saved detail, no replay
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from f1lib.driver_ratings import DriverRatings
from f1lib.race_forecast import RaceForecaster, _is_finish

DETAIL = Path("data/backtest_race_forecast_detail.csv")
SUMMARY = Path("data/backtest_race_forecast.csv")
ODDS = Path("data/odds_snapshots.csv")

EPS = 1e-6
# Outcome, its threshold on finishing position, and the market that prices it.
TARGETS = [("win", 1, "win"), ("podium", 3, "podium"), ("points", 10, None)]


# ─────────────────────────────────────────────────────────────
# scoring primitives
# ─────────────────────────────────────────────────────────────

def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def logloss(p, y) -> float:
    p, y = np.clip(np.asarray(p, float), EPS, 1 - EPS), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def skill(score: float, ref: float) -> float:
    """Fraction of the reference's error removed. 0 = no better, 1 = perfect."""
    return float("nan") if not ref else float(1.0 - score / ref)


# ─────────────────────────────────────────────────────────────
# the replay
# ─────────────────────────────────────────────────────────────

def _parse_variant(items: list[str] | None) -> dict:
    """--variant sc_mixture=1 sc_noise_mult=1.3 -> forecaster overrides.

    A variant is scored, never saved: the point is to find out whether a
    change earns its place across seasons before any default moves.
    """
    out: dict = {}
    for it in items or []:
        k, _, v = it.partition("=")
        k, v = k.strip(), v.strip()
        if v.lower() in ("1", "true", "yes", "on"):
            out[k] = True
        elif v.lower() in ("0", "false", "no", "off"):
            out[k] = False
        else:
            out[k] = float(v)
    return out


def _variant_tag(variant: dict) -> str:
    """Filename-safe label for a variant's detail file."""
    return "_".join(f"{k}{v}" for k, v in sorted(variant.items())).replace(
        ".", "p")


def replay(seasons: tuple[int, ...] | None, variant: dict | None = None) -> pd.DataFrame:
    """One row per driver-race: what was forecast, and what happened.

    Saved rather than only summarised, because every later question —
    calibration, market comparison, per-team breakdowns — is a re-read of this
    table and must not need another hour of simulation.
    """
    from f1lib.pace_features import event_measurements
    from f1lib.pace_model import PaceModel

    m, rf, dr = (PaceModel(), RaceForecaster(**(variant or {})),
                 DriverRatings())
    res = rf._results.copy()
    res["finished"] = _is_finish(res["Status"])

    groups = list(dr.pace[dr.pace["kind"] == "race"].groupby(["season", "event"]))
    if seasons:
        groups = [g for g in groups if int(g[0][0]) in seasons]

    rows: list[dict] = []
    for i, ((season, event), _g) in enumerate(groups, 1):
        rnd = m.round_of(season, event)
        if rnd is None:
            continue
        try:
            meas, _ = event_measurements(season, event)
            if meas is None or meas.empty:
                continue
            stages = m.predict_weekend(season, event, measurements=meas, round_=rnd)
            final = list(stages.values())[-1]
            race_pred = m.driver_predictions(final, dr.roster(season, event),
                                             "longrun", as_of=(season, rnd))
        except Exception as exc:
            print(f"  [{i}/{len(groups)}] {season} {event[:28]:30s} SKIP "
                  f"({type(exc).__name__})", flush=True)
            continue
        if race_pred is None or race_pred.empty:
            continue

        rr = res[(res["season"] == season) & (res["event_name"] == event)].copy()
        rr["driver"] = rr["Abbreviation"]
        rr = rr.dropna(subset=["GridPosition", "Position"])
        if len(rr) < 8:
            continue
        grid = rr.set_index("driver")["GridPosition"].astype(int).to_dict()

        fc = rf.forecast(race_pred, event=event, grid=grid)
        if fc.empty:
            continue
        merged = fc.merge(
            rr[["driver", "Position", "GridPosition", "finished"]], on="driver")
        if len(merged) < 8:
            continue

        merged["season"], merged["event"], merged["round"] = season, event, rnd
        merged["n_starters"] = len(merged)
        merged = merged.rename(columns={"Position": "finish_actual",
                                        "GridPosition": "grid"})
        merged["dnf_actual"] = (~merged["finished"].astype(bool)).astype(int)
        for name, cut, _mkt in TARGETS:
            merged[f"{name}_actual"] = (merged["finish_actual"] <= cut).astype(int)
        rows.append(merged)
        print(f"  [{i}/{len(groups)}] {season} {event[:28]:30s} "
              f"{len(merged)} drivers", flush=True)

    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    keep = ["season", "round", "event", "driver", "team", "grid", "n_starters",
            "p_win", "p_podium", "p_points", "e_finish", "p_dnf",
            "finish_actual", "dnf_actual",
            "win_actual", "podium_actual", "points_actual"]
    return out[keep]


# ─────────────────────────────────────────────────────────────
# baselines
# ─────────────────────────────────────────────────────────────

def add_climatology(d: pd.DataFrame) -> pd.DataFrame:
    """The field base rate. p_win = 1/n and so on — no skill whatsoever."""
    for name, cut, _ in TARGETS:
        d[f"clim_{name}"] = np.minimum(cut, d["n_starters"]) / d["n_starters"]
    return d


def add_grid_baseline(d: pd.DataFrame) -> pd.DataFrame:
    """P(outcome | grid slot), fitted on strictly EARLIER races only.

    Expanding window rather than a global fit: a baseline that has seen the
    race it is being scored on would flatter itself, and the whole point of
    this reference is to be beaten honestly. Slots are pooled into buckets so
    the estimate is stable while the window is still short.
    """
    d = d.sort_values(["season", "round"]).reset_index(drop=True)
    d["grid_bucket"] = pd.cut(d["grid"], [0, 1, 2, 3, 5, 8, 12, 16, 30],
                              labels=False)
    order = d[["season", "round"]].drop_duplicates().sort_values(
        ["season", "round"]).reset_index(drop=True)
    for name, _cut, _ in TARGETS:
        d[f"gridb_{name}"] = np.nan
    for _, row in order.iterrows():
        s, r = int(row["season"]), int(row["round"])
        cur = (d["season"] == s) & (d["round"] == r)
        past = (d["season"] < s) | ((d["season"] == s) & (d["round"] < r))
        if past.sum() < 200:                    # too little history to fit
            continue
        p = d[past]
        for name, _cut, _ in TARGETS:
            rate = p.groupby("grid_bucket")[f"{name}_actual"].mean()
            glob = p[f"{name}_actual"].mean()
            d.loc[cur, f"gridb_{name}"] = (
                d.loc[cur, "grid_bucket"].map(rate).fillna(glob).values)
    return d


def add_market(d: pd.DataFrame, odds_path: Path = ODDS) -> pd.DataFrame:
    """The last de-vigged price before lights out, per driver and market.

    Deliberately the LAST pre-lock snapshot: it is the market's final word,
    which is the strongest version of the benchmark. `pre_lock` keeps it
    strictly before the race, and the overround band drops books that are
    stale or half-empty — both filters are required, see read_local.md.
    """
    for _n, _c, mkt in TARGETS:
        if mkt:
            d[f"mkt_{mkt}"] = np.nan
    if not odds_path.exists():
        return d
    o = pd.read_csv(odds_path, low_memory=False)
    o = o[(o["pre_lock"] == True) & o["overround"].between(0.9, 1.25)
          & o["p_devig_power"].notna() & o["event"].notna()
          & o["driver"].notna() & (o["driver"] != "FIELD")]
    if o.empty:
        return d
    o = o.sort_values("hours_to_lock")           # smallest = closest to lights out
    for name, _cut, mkt in TARGETS:
        if not mkt:
            continue
        s = o[o["market"] == mkt]
        if s.empty:
            continue
        last = s.groupby(["season", "event", "driver"], as_index=False).head(1)
        # Several bookmakers can price the same driver; average them.
        agg = last.groupby(["season", "event", "driver"], as_index=False)[
            "p_devig_power"].mean().rename(columns={"p_devig_power": f"mkt_{mkt}"})
        d = d.drop(columns=[f"mkt_{mkt}"]).merge(
            agg, on=["season", "event", "driver"], how="left")
    return d


# ─────────────────────────────────────────────────────────────
# reporting
# ─────────────────────────────────────────────────────────────

def scorecard(d: pd.DataFrame) -> pd.DataFrame:
    """Scores per EVENT, per season, and overall, for every reference.

    Per-event rows exist because a season average answers "should I trust this
    model" but not "how did it do at Monaco" — and the two diverge sharply,
    since a single wet or chaotic race can carry a whole season's mean. The
    dashboard reads the event rows; nothing else recomputes them, which is
    what keeps the card and this file from drifting apart.

    `scope` distinguishes them: event | season | all.
    """
    out = []
    groups = ([(("event", s, e), sub) for (s, e), sub in d.groupby(["season", "event"])]
              + [(("season", s, None), sub) for s, sub in d.groupby("season")]
              + [(("all", "ALL", None), d)])
    for (scope, label, ev), sub in groups:
        row = {"scope": scope, "season": label, "event": ev,
               "round": (int(sub["round"].iloc[0])
                         if scope == "event" and "round" in sub.columns
                         and pd.notna(sub["round"].iloc[0]) else None),
               "races": sub.groupby(["season", "event"]).ngroups,
               "rows": len(sub)}
        for name, _cut, mkt in TARGETS:
            y = sub[f"{name}_actual"].values
            row[f"brier_{name}"] = brier(sub[f"p_{name}"], y)
            row[f"logloss_{name}"] = logloss(sub[f"p_{name}"], y)
            row[f"brier_clim_{name}"] = brier(sub[f"clim_{name}"], y)
            g = sub.dropna(subset=[f"gridb_{name}"])
            row[f"brier_grid_{name}"] = (
                brier(g[f"gridb_{name}"], g[f"{name}_actual"]) if len(g) else np.nan)
            if mkt and f"mkt_{mkt}" in sub:
                mm = sub.dropna(subset=[f"mkt_{mkt}"])
                row[f"n_mkt_{name}"] = len(mm)
                row[f"brier_mkt_{name}"] = (
                    brier(mm[f"mkt_{mkt}"], mm[f"{name}_actual"]) if len(mm) else np.nan)
                # like-for-like: the model restricted to the same driver-races
                row[f"brier_vsmkt_{name}"] = (
                    brier(mm[f"p_{name}"], mm[f"{name}_actual"]) if len(mm) else np.nan)
        row["brier_dnf"] = brier(sub["p_dnf"], sub["dnf_actual"])
        row["mae_finish"] = float(np.mean(np.abs(sub["e_finish"] - sub["finish_actual"])))
        row["rmse_finish"] = float(np.sqrt(np.mean(
            (sub["e_finish"] - sub["finish_actual"]) ** 2)))
        out.append(row)
    return pd.DataFrame(out)


def print_report(d: pd.DataFrame, sc: pd.DataFrame) -> None:
    a = sc[sc["scope"] == "all"].iloc[0]
    print(f"\n{'=' * 74}\nOUTCOME SCORECARD  —  {int(a['races'])} races, "
          f"{int(a['rows']):,} driver-races\n{'=' * 74}")

    print(f"\n{'':10s} {'Brier':>8s} {'logloss':>9s} | {'climatol.':>10s} "
          f"{'grid':>8s} | {'skill vs':>9s} {'skill vs':>9s}")
    print(f"{'':10s} {'model':>8s} {'model':>9s} | {'Brier':>10s} {'Brier':>8s} "
          f"| {'clim':>9s} {'grid':>9s}")
    for name, _c, _m in TARGETS:
        b, c, g = a[f"brier_{name}"], a[f"brier_clim_{name}"], a[f"brier_grid_{name}"]
        print(f"  {name:8s} {b:>8.4f} {a[f'logloss_{name}']:>9.4f} | {c:>10.4f} "
              f"{g:>8.4f} | {skill(b, c):>8.1%} {skill(b, g):>9.1%}")
    print(f"  {'dnf':8s} {a['brier_dnf']:>8.4f}")
    print(f"\n  e_finish   MAE {a['mae_finish']:.3f} positions   "
          f"RMSE {a['rmse_finish']:.3f}")

    # Both comparisons get a confidence interval rather than a bare gap. On a
    # single season the model appeared to beat the market on p_win; over five
    # the sign flipped. Point estimates at this scale are not evidence.
    print_compare(d, "AGAINST THE GRID BASELINE  (P(outcome | grid slot), prior races only)",
                  [(n, f"p_{n}", f"gridb_{n}") for n, _c, _m in TARGETS])
    print_compare(d, "AGAINST THE MARKET  (last de-vigged price before lights out)",
                  [(n, f"p_{n}", f"mkt_{m}") for n, _c, m in TARGETS if m])

    calibration_slope(d)
    reliability(d)


def bootstrap_compare(d: pd.DataFrame, pcol: str, qcol: str, ycol: str,
                      n_boot: int = 20000, seed: int = 7) -> dict:
    """Cluster bootstrap of Brier(p) - Brier(q), resampling RACES.

    The race is the unit, not the driver-race: one result moves all ~20 of a
    race's rows together, so a row-level bootstrap treats 20 correlated
    observations as 20 independent ones and will call noise significant. That
    matters here because the gaps in question are ~0.005 of Brier — exactly
    the size that looks like a finding on one season and evaporates on five.

    Brier is a mean of squared errors, so each race reduces to (error sum,
    count) and the resample is exact rather than approximated.
    """
    s = d.dropna(subset=[pcol, qcol, ycol])
    if s.empty:
        return {}
    g = s.groupby(s["season"].astype(str) + " " + s["event"])
    sp = g.apply(lambda x: ((x[pcol] - x[ycol]) ** 2).sum(), include_groups=False).values
    sq = g.apply(lambda x: ((x[qcol] - x[ycol]) ** 2).sum(), include_groups=False).values
    cnt = g.size().values.astype(float)
    k = len(cnt)
    if k < 5:
        return {}
    idx = np.random.default_rng(seed).integers(0, k, size=(n_boot, k))
    diffs = (sp[idx].sum(1) - sq[idx].sum(1)) / cnt[idx].sum(1)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"n": len(s), "races": k,
            "p": brier(s[pcol], s[ycol]), "q": brier(s[qcol], s[ycol]),
            "diff": brier(s[pcol], s[ycol]) - brier(s[qcol], s[ycol]),
            "lo": float(lo), "hi": float(hi),
            "race_wins": int(((sp / cnt) < (sq / cnt)).sum()),
            "significant": bool(hi < 0 or lo > 0)}


def print_compare(d: pd.DataFrame, title: str,
                  pairs: list[tuple[str, str, str]]) -> None:
    print(f"\n{'-' * 74}\n{title}\n{'-' * 74}")
    print(f"  {'target':8s} {'races':>6s} {'n':>6s} {'model':>8s} {'ref':>8s} "
          f"{'diff':>9s} {'95% CI':>21s} {'wins':>9s}  verdict")
    for name, pcol, qcol in pairs:
        r = bootstrap_compare(d, pcol, qcol, f"{name}_actual")
        if not r:
            continue
        who = "model" if r["diff"] < 0 else "ref"
        sig = "SIGNIFICANT" if r["significant"] else "not significant"
        print(f"  {name:8s} {r['races']:>6d} {r['n']:>6d} {r['p']:>8.4f} "
              f"{r['q']:>8.4f} {r['diff']:>+9.4f} "
              f"[{r['lo']:>+8.4f},{r['hi']:>+8.4f}] "
              f"{r['race_wins']:>4d}/{r['races']:<4d} {who} better, {sig}")


def calibration_slope(d: pd.DataFrame) -> None:
    """Regress outcome on stated probability.

    Slope > 1 means the predictions are COMPRESSED toward the middle — the
    model is not confident enough and its distribution is too flat. Slope < 1
    is the opposite. Brier alone cannot separate these from ordinary error,
    and they call for opposite fixes, so it is worth its own line.
    """
    print(f"\n{'-' * 74}\nSHARPNESS  (actual ~ a + b x predicted)\n"
          f"  b > 1 = under-separated, predictions too timid\n"
          f"  b < 1 = over-separated, predictions too bold\n{'-' * 74}")
    for name, _c, _m in TARGETS:
        s = d.dropna(subset=[f"p_{name}"])
        b, a = np.polyfit(s[f"p_{name}"], s[f"{name}_actual"], 1)
        flag = "under-separated" if b > 1.05 else (
            "over-separated" if b < 0.95 else "well separated")
        print(f"  p_{name:8s} slope {b:>6.3f}  intercept {a:>+8.4f}   {flag}")


def reliability(d: pd.DataFrame, target: str = "podium") -> None:
    """Does a stated 30% happen 30% of the time? Brier cannot tell you: a
    model can be sharp and biased, or calibrated and useless."""
    print(f"\n{'-' * 74}\nCALIBRATION of p_{target}\n{'-' * 74}")
    bins = [0, .02, .05, .1, .2, .35, .5, .7, .9, 1.01]
    for lbl, col in (("model", f"p_{target}"), ("market", f"mkt_{target}")):
        if col not in d or d[col].notna().sum() < 50:
            continue
        s = d.dropna(subset=[col])
        s = s.assign(b=pd.cut(s[col], bins))
        g = s.groupby("b", observed=True).agg(
            n=(f"{target}_actual", "size"), predicted=(col, "mean"),
            actual=(f"{target}_actual", "mean"))
        g = g[g["n"] >= 10]
        worst = (g["actual"] - g["predicted"]).abs().max()
        print(f"\n  {lbl}  (max deviation {worst:.3f})")
        for idx, r in g.iterrows():
            bar = "#" * int(round(r["actual"] * 40))
            print(f"    {str(idx):>14s} n={int(r['n']):>5d} "
                  f"pred {r['predicted']:.3f}  actual {r['actual']:.3f} {bar}")


# ─────────────────────────────────────────────────────────────
# the two rank tests (unchanged in substance)
# ─────────────────────────────────────────────────────────────

def combination_test() -> None:
    """Is the blend sound? Uses ACTUAL pace and ACTUAL grid, so pace-prediction
    error is out of the picture and only the combination is on trial."""
    rf, dr = RaceForecaster(), DriverRatings()
    res = rf._results.copy()
    res["fin"] = res["Position"]
    rows = []
    for (season, event), g in dr.pace[dr.pace["kind"] == "race"].groupby(
            ["season", "event"]):
        prank = g.set_index("driver")["gap_pct"].rank()
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
        rows.append({"rho_grid": spearmanr(grid.values, a).correlation,
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


# ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seasons", type=int, nargs="+")
    ap.add_argument("--rank-tests-only", action="store_true")
    ap.add_argument("--report", action="store_true",
                    help="re-score the saved detail file without replaying")
    ap.add_argument("--variant", nargs="+", metavar="KEY=VAL",
                    help="RaceForecaster overrides to score, e.g. "
                         "--variant sc_mixture=1 (writes to a separate detail "
                         "file so the baseline is never overwritten)")
    args = ap.parse_args()

    combination_test()
    if args.rank_tests_only:
        return 0

    if args.report:
        if not DETAIL.exists():
            print(f"\n{DETAIL} not present - run without --report first.")
            return 2
        d = pd.read_csv(DETAIL)
        print(f"\nRe-scoring {len(d):,} saved driver-races (no replay).")
    else:
        print(f"\n== Replaying races (predicted pace, as-of; actual grid) ==")
        variant = _parse_variant(args.variant)
        if variant:
            print(f"   variant: {variant}")
        d = replay(tuple(args.seasons) if args.seasons else None, variant)
        if d.empty:
            print("No races could be replayed.")
            return 1
        # A variant NEVER writes over the baseline. Without this the thing
        # being compared against silently becomes the thing being tested.
        detail = DETAIL if not variant else DETAIL.with_name(
            f"{DETAIL.stem}__{_variant_tag(variant)}.csv")
        detail.parent.mkdir(parents=True, exist_ok=True)
        d.to_csv(detail, index=False)
        print(f"\nWrote {detail} ({len(d):,} driver-races)")

    d = add_climatology(d)
    d = add_grid_baseline(d)
    d = add_market(d)
    sc = scorecard(d)
    if args.report or not _parse_variant(args.variant):
        sc.to_csv(SUMMARY, index=False)
        print(f"\nWrote {SUMMARY} ({len(sc)} rows: per season + ALL)")
    print_report(d, sc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
