"""Weekend decomposition: where a team's points actually came from.

Every card on the RACE tab measures one mechanism in isolation — quali, the
start, pit stops, strategy, incidents — and nobody adds them up. This module
does the accounting: for one team-weekend,

    actual points − expected points  =  quali + start + pit crew + SC luck
                                        + incidents + on-track residual

with "expected" defined by the dashboard's own race forecaster. The result is
an ACCOUNTING decomposition, not a causal proof: each term is the change in
Monte-Carlo expected points when one piece of information is swapped in, taken
in a fixed order (an Oaxaca-style sequential decomposition — terms depend on
that order, which is why the order is chronological and printed on the card).

The expectation checkpoints
---------------------------
E_pace  expected points from car+driver speed alone: the post-practice pace
        posterior simulated through qualifying AND the race (grid sampled from
        the one-lap prediction). "What should this package score here?"
E_grid  the same race simulation started from the ACTUAL grid.
        → quali execution = E_grid − E_pace  (out-qualified the car, or not)
E_lap1  started from the ACTUAL positions after lap 1.
        → start = E_lap1 − E_grid
Actual  what the archive says they scored (GP only, sprint excluded).

The race-phase gap (Actual − E_lap1) is then split into measured pieces:

incidents   for every retirement, minus the driver's conditional expected
            points had they NOT retired (from the E_lap1 simulation's own
            no-DNF sims). Cause labelled from race control when known.
pit crew    the team's summed stationary-time delta vs the field median stop
            of that race (normal stops only — a stop over _CREW_CAP_S is a
            penalty or repair, not the crew), converted to points.
SC luck     seconds saved by stops taken under SC/VSC relative to the field
            mean saving, converted to points. Timing luck, not skill.
on-track    the remainder: race pace, strategy calls, traffic, and everything
            not measured above. Closed-form residual, so the terms always sum
            exactly to Actual − E_pace.

Seconds → points uses two measured race-local quantities: the median gap
between consecutive lead-lap finishers (how many seconds one position is
worth THAT day) and the points-table slope at the team's actual finishing
positions (a backmarker's slow stop prices to ~0 points, correctly).

Honest limits: the forecaster prices DNFs at a flat field rate, so E_pace is
not reliability-adjusted per team; sprint points are out of scope; pre-2025
seasons ignore the fastest-lap point in the expectation (the archive's actual
points still include it); and the sequential order means e.g. a car wrecked on
lap 1 books under incidents only if it never set a lap-1 position (otherwise
the drop shows in start). Coarse pieces are labelled coarse on the card.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from f1lib.pace_features import canon

logger = logging.getLogger(__name__)

HIST = Path("data/historical_results")
DECOMP_PATH = Path("data/weekend_decomp.csv")

# 25-18-15-12-10-8-6-4-2-1, unchanged since 2010. The 2019-2024 fastest-lap
# point is deliberately not modelled in the expectation (see module docstring).
_POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}

# A stationary time above this is a penalty being served or a repair — the
# pit CREW didn't cause it, so it stays out of the crew term (→ on-track).
_CREW_CAP_S = 15.0

# Fraction of the green-flag pit loss still paid when stopping under a full
# safety car (matches the RACE tab's strategy simulator) / a VSC. The VSC
# figure is an assumption, not a measurement: the field slows to a delta, so
# roughly a third of the loss comes back.
_SC_FACTOR = 0.45
_VSC_FACTOR = 0.65

_FALLBACK_GAP_S = 3.0     # s per position when lead-lap gaps can't be measured
_FALLBACK_PIT_LOSS_S = 20.0

_COMPONENTS = ("d_quali", "d_start", "d_pit", "d_sc", "d_incidents", "d_ontrack")


def _points_vector(finish: np.ndarray, dnf: np.ndarray) -> np.ndarray:
    """(n_sims, k) points for a finish-position matrix; retirements score 0."""
    pts = np.zeros_like(finish, dtype=float)
    for pos, p in _POINTS.items():
        pts[finish == pos] = p
    pts[dnf] = 0.0
    return pts


def _exp_points(sim: dict) -> pd.Series:
    """Expected points per driver from a RaceForecaster.simulate() result."""
    pts = _points_vector(sim["finish"], sim["dnf"])
    return pd.Series(pts.mean(axis=0), index=sim["drivers"])


def _exp_points_no_own_dnf(sim: dict, driver: str) -> float:
    """Driver's expected points over the sims where THEY didn't retire."""
    try:
        i = sim["drivers"].index(driver)
    except ValueError:
        return 0.0
    keep = ~sim["dnf"][:, i]
    if not keep.any():
        return 0.0
    pts = _points_vector(sim["finish"][keep], sim["dnf"][keep])
    return float(pts[:, i].mean())


def _is_finished(status: pd.Series) -> pd.Series:
    s = status.fillna("").astype(str)
    return (s.str.startswith("Finished") | s.str.startswith("Lapped")
            | s.str.match(r"^\+\d"))


def _points_slope(pos: float) -> float:
    """Points gained per position around `pos` (finite difference on the
    table). Zero outside the points window — a P15 team's stop delta is
    worth nothing, and the conversion must say so."""
    if not np.isfinite(pos):
        return 0.0
    p = int(round(pos))
    lo = _POINTS.get(p + 1, 0)
    hi = _POINTS.get(p - 1, _POINTS.get(1, 25) if p <= 1 else 0)
    return (hi - lo) / 2.0


def _driver_prefix(raw_driver: pd.Series) -> pd.Series:
    """'NOR-McLaren' → 'NOR' (raw cache Driver column)."""
    return raw_driver.astype(str).str.split("-").str[0]


def _position_seconds(res: pd.DataFrame) -> float:
    """Median gap (s) between consecutive lead-lap finishers — what one track
    position was worth in this race. The archive's Time column is the winner's
    total for P1 and the gap TO the winner for every other lead-lap finisher,
    so consecutive differences of the sorted gaps are exactly the inter-car
    gaps at the flag. Falls back to a constant when fewer than four cars
    finished on the lead lap (red flags, attrition)."""
    lead = res[res["Status"].fillna("").astype(str).str.startswith("Finished")]
    gaps_to_winner = pd.to_numeric(lead.loc[lead["Position"] > 1, "Time"],
                                   errors="coerce").dropna().sort_values()
    if len(gaps_to_winner) < 4:
        return _FALLBACK_GAP_S
    gaps = np.diff(np.concatenate([[0.0], gaps_to_winner.to_numpy()]))
    med = float(np.median(gaps))
    return float(np.clip(med, 1.0, 30.0)) if np.isfinite(med) else _FALLBACK_GAP_S


def _stop_discounts(rl: pd.DataFrame, stops: pd.DataFrame) -> pd.Series:
    """Per-stop fraction of the pit loss actually paid (1 green, less under
    SC/VSC), aligned to `stops`' index, from the in-lap's TrackStatus."""
    if rl is None or rl.empty or stops.empty:
        return pd.Series(1.0, index=stops.index)
    t = rl[["Driver", "LapNo", "TrackStatus"]].copy()
    t["drv"] = _driver_prefix(t["Driver"])
    status = {(r.drv, int(r.LapNo)): str(r.TrackStatus)
              for r in t.itertuples(index=False) if pd.notna(r.LapNo)}
    out = []
    for r in stops.itertuples(index=False):
        st = status.get((r.driver, int(r.lap)), "")
        if "4" in st:                       # full safety car
            out.append(_SC_FACTOR)
        elif "6" in st or "7" in st:        # VSC (deployed / ending)
            out.append(_VSC_FACTOR)
        else:
            out.append(1.0)
    return pd.Series(out, index=stops.index)


def decompose_event(season: int, event: str, *, model=None, forecaster=None,
                    rng: np.random.Generator | None = None) -> pd.DataFrame:
    """One row per team for one Grand Prix. Empty frame when the event can't
    be decomposed (no cached race, no pace-table entry, ratings missing)."""
    import f1lib.data_loader as dl
    from f1lib.incidents import classify_retirement

    season = int(season)

    # ── actual outcome ────────────────────────────────────────
    res = pd.read_parquet(HIST / "race_results_all.parquet")
    res = res[(res["season"] == season) & (res["event_name"] == event)].copy()
    if res.empty:
        return pd.DataFrame()
    res["team"] = res["TeamName"].map(canon)
    res = res[~res["Status"].fillna("").str.startswith("Did not start")]
    res["finished"] = _is_finished(res["Status"])

    # ── cached race laps (lap-1 order, gaps, stop track status) ──
    key = dl._session_key(str(season), event, "Race")
    lap_path = dl._cache_paths(key)["laps"]
    rl = pd.read_parquet(lap_path) if lap_path.exists() else None

    # ── the expectation operator: pace model + forecaster ─────
    if model is None:
        from f1lib.pace_model import PaceModel
        model = PaceModel()
    if forecaster is None:
        from f1lib.race_forecast import RaceForecaster
        forecaster = RaceForecaster()
    try:
        stages = model.predict_weekend(season, event)
    except ValueError:
        return pd.DataFrame()
    final = stages[list(stages)[-1]]        # post-practice, outcome-blind
    round_ = model.round_of(season, event) or model.next_round_of(season)
    roster = res[["Abbreviation", "team"]].rename(
        columns={"Abbreviation": "driver"}).drop_duplicates()
    dpred = model.driver_predictions(final, roster, "longrun",
                                     as_of=(season, round_))
    qpred = model.driver_predictions(final, roster, "onelap",
                                     as_of=(season, round_))
    if dpred.empty or dpred["team"].nunique() < max(6, res["team"].nunique() - 2):
        return pd.DataFrame()
    rng = rng or np.random.default_rng(int(season) * 100 + int(round_))
    k = len(dpred)

    # grids for the three checkpoints
    grid_actual = {}
    for r in res.itertuples(index=False):
        gp = r.GridPosition
        grid_actual[r.Abbreviation] = int(gp) if pd.notna(gp) and gp > 0 else k
    lap1 = dict(grid_actual)
    if rl is not None and not rl.empty:
        l1 = rl[rl["LapNo"] == 1].copy()
        l1["drv"] = _driver_prefix(l1["Driver"])
        for r in l1.dropna(subset=["Position"]).itertuples(index=False):
            lap1[r.drv] = int(r.Position)   # missing lap-1 row keeps grid pos

    sim_pace = forecaster.simulate(dpred, event=event, quali_pred=qpred, rng=rng)
    sim_grid = forecaster.simulate(dpred, event=event, grid=grid_actual, rng=rng)
    sim_lap1 = forecaster.simulate(dpred, event=event, grid=lap1, rng=rng)
    if not all((sim_pace, sim_grid, sim_lap1)):
        return pd.DataFrame()
    e_pace, e_grid, e_lap1 = map(_exp_points, (sim_pace, sim_grid, sim_lap1))
    team_of = dpred.set_index("driver")["team"]

    def _team(s: pd.Series) -> pd.Series:
        return s.groupby(team_of.reindex(s.index)).sum()

    # ── measured race-phase pieces ────────────────────────────
    # incidents: what each retiree would have scored, by their own no-DNF sims
    d_inc, causes = {}, {}
    retired = res[~res["finished"]]
    for r in retired.itertuples(index=False):
        lost = _exp_points_no_own_dnf(sim_lap1, r.Abbreviation)
        d_inc[r.team] = d_inc.get(r.team, 0.0) - lost
        info = classify_retirement(season, event, r.Abbreviation,
                                   r.Laps if pd.notna(r.Laps) else None)
        cause = (info or {}).get("cause") or "unclassified"
        causes.setdefault(r.team, []).append(f"{r.Abbreviation} ({cause})")

    # pit crew + SC luck, in seconds first
    pit_delta_s, sc_saved_s = {}, {}
    try:
        pl = pd.read_csv("data/pit_league.csv")
        pl = pl[(pl["season"] == season) & (pl["meeting"] == event)].copy()
    except OSError:
        pl = pd.DataFrame()
    if not pl.empty:
        pl["team"] = pl["team"].map(canon)
        normal = pl[pl["stationary_s"] < _CREW_CAP_S]
        med_stop = float(normal["stationary_s"].median()) if not normal.empty else np.nan
        if np.isfinite(med_stop):
            pit_delta_s = ((normal["stationary_s"] - med_stop)
                           .groupby(normal["team"]).sum().to_dict())
        pit_loss = _FALLBACK_PIT_LOSS_S
        try:
            rs = pd.read_csv("data/race_stats.csv")
            row = rs[(rs["season"] == season) & (rs["meeting"] == event)]
            if not row.empty and np.isfinite(row["pit_loss_s"].iloc[0]):
                pit_loss = float(row["pit_loss_s"].iloc[0])
        except OSError:
            pass
        disc = _stop_discounts(rl, pl)
        pl["saved_s"] = (1.0 - disc) * pit_loss
        sc_saved_s = pl.groupby("team")["saved_s"].sum().to_dict()

    # seconds → points: race-local position value × team-local points slope
    gap_s = _position_seconds(res)
    slope = {}
    for team, g in res.groupby("team"):
        pos = g.loc[g["finished"], "Position"]
        if pos.empty:                        # both cars out: use expectation
            drs = team_of[team_of == team].index
            pos = pd.Series(
                [sim_lap1["finish"][:, sim_lap1["drivers"].index(d)].mean()
                 for d in drs if d in sim_lap1["drivers"]])
        slope[team] = float(np.mean([_points_slope(p) for p in pos])) \
            if not pos.empty else 0.0

    # ── assemble, closing the residual exactly ────────────────
    actual = res.groupby("team")["Points"].sum()
    t_pace, t_grid, t_lap1 = _team(e_pace), _team(e_grid), _team(e_lap1)
    # luck is relative: centre SC savings on the whole field, teams that
    # never stopped included (their saving is genuinely zero)
    field_saved = (float(np.mean([sc_saved_s.get(t, 0.0)
                                  for t in actual.index]))
                   if sc_saved_s else 0.0)
    rows = []
    for team in sorted(actual.index):
        if team not in t_pace.index:
            continue
        a = float(actual[team])
        e0, e1, e2 = float(t_pace[team]), float(t_grid[team]), float(t_lap1[team])
        pit_s = float(pit_delta_s.get(team, 0.0))
        sc_s = float(sc_saved_s.get(team, 0.0)) - field_saved
        d = {
            "d_quali": e1 - e0,
            "d_start": e2 - e1,
            "d_pit": -pit_s / gap_s * slope[team],
            "d_sc": sc_s / gap_s * slope[team],
            "d_incidents": d_inc.get(team, 0.0),
        }
        d["d_ontrack"] = (a - e0) - sum(d.values())
        rows.append({
            "season": season, "round": int(round_), "event": event,
            "team": team, "exp_points": round(e0, 2), "actual_points": a,
            **{c: round(v, 2) for c, v in d.items()},
            "pit_delta_s": round(pit_s, 1), "sc_saved_s": round(sc_s, 1),
            "retirements": "; ".join(causes.get(team, [])),
            "gap_s_per_pos": round(gap_s, 2),
        })
    return pd.DataFrame(rows)


def decomp_df() -> pd.DataFrame:
    """The shipped table; empty frame (with columns) when not built."""
    cols = ["season", "round", "event", "team", "exp_points", "actual_points",
            *_COMPONENTS, "pit_delta_s", "sc_saved_s", "retirements",
            "gap_s_per_pos"]
    if not DECOMP_PATH.exists():
        return pd.DataFrame(columns=cols)
    try:
        return pd.read_csv(DECOMP_PATH)
    except Exception as exc:
        logger.warning("weekend_decomp unreadable: %s", exc)
        return pd.DataFrame(columns=cols)
