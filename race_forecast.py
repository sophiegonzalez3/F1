"""Race-result forecast: pace + grid + overtaking difficulty → finishing order.

Pace tells you who is fast; it does not tell you who finishes where. Two more
things decide that: where a driver STARTS (a fast car buried in the pack may
not get past) and how hard the CIRCUIT is to overtake on (Monaco locks the
grid in; Bahrain lets pace through). This module turns the per-driver race
pace from pace_model into a distribution over finishing positions by
simulating the race many times.

Per simulation
--------------
  1. sample each driver's race pace from their posterior — teammates share
     their car's draw (a strong car lifts both), then differ by the driver
     rating and event-day noise (pace_model.driver_outcome_probs machinery).
  2. establish the grid: the real starting order once qualifying is known,
     otherwise a grid sampled the same way from the one-lap prediction, so
     grid uncertainty flows into the result before Saturday.
  3. blend pace and grid by the circuit's passability: expected running order
     = grid + pull·(pace_rank − grid), where pull∈[0,1] is how much pace
     overcomes track position (1 = pace wins, 0 = grid sticks). Add race-day
     shuffle noise.
  4. knock out cars with a base DNF probability (reliability + incidents);
     a retirement drops a car behind the finishers.
  then rank to integer positions.

Passability is measured empirically per circuit from the historical results
archive as the rank correlation between grid and finish among classified
finishers (high correlation = sticky = hard to pass), shrunk toward the field
average for circuits with little history.

What this does NOT model: pit-strategy calls, weather changes mid-race,
per-team reliability differences, and specific incidents. DNFs are a single
field-average rate. It is a PACE-and-track forecast, honest about that.

Entry point
-----------
    from race_forecast import RaceForecaster
    rf = RaceForecaster()
    out = rf.forecast(race_pred, quali_pred=quali_pred, event="Monaco Grand Prix")
    # out: driver, team, p_win, p_podium, p_points, e_finish, p_dnf
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pace_features import canon

logger = logging.getLogger(__name__)

HIST = Path("data/historical_results")

DEFAULTS = dict(
    n_sims=20000,
    race_noise=2.2,        # positions of race-day shuffle sd (strategy, traffic)
    dnf_rate=0.11,         # base per-car retirement probability
    pull_lo=0.20,          # passability floor (even Monaco lets a little pace through)
    pull_hi=0.85,          # ceiling (even Monza isn't a pure pace sort)
    shrink_races=8.0,      # pseudo-races pulling circuit stickiness to the mean
)

_DNF_KEYWORDS = ("Accident", "Collision", "Spun", "Retired", "Withdrew",
                 "Disqualified", "Engine", "Gearbox", "Hydraulics",
                 "Power", "Brakes", "Suspension", "Transmission", "Electrical",
                 "Overheating", "Mechanical", "Puncture", "Wheel", "Fuel",
                 "Water", "Oil", "Clutch", "Driveshaft", "Damage", "Battery",
                 "Exhaust", "Radiator", "Vibrations", "Debris", "Steering")


def _is_finish(status: pd.Series) -> pd.Series:
    s = status.astype(str)
    return (s.str.startswith("Finished") | s.str.match(r"^\+\d")) \
        | (~s.str.contains("|".join(_DNF_KEYWORDS), case=False, na=False)
           & ~s.str.contains("Lap", na=False))


class RaceForecaster:
    def __init__(self, **overrides):
        self.p = {**DEFAULTS, **overrides}
        self._results = self._load_results()
        self._pull, self._global_pull = self._circuit_passability()
        self._event_to_circuit = self._event_map()

    # ── historical calibration ────────────────────────────────

    def _load_results(self) -> pd.DataFrame:
        frames = []
        for f in ("race_results_all.parquet",):
            p = HIST / f
            if p.exists():
                frames.append(pd.read_parquet(p))
        if not frames:
            return pd.DataFrame()
        r = pd.concat(frames, ignore_index=True)
        r = r.dropna(subset=["GridPosition", "Position"])
        return r[r["GridPosition"] > 0].copy()

    def _event_map(self) -> dict[str, str]:
        if self._results.empty or "circuit_key" not in self._results.columns:
            return {}
        return (self._results.dropna(subset=["circuit_key"])
                .drop_duplicates("event_name")
                .set_index("event_name")["circuit_key"].to_dict())

    def _circuit_passability(self) -> tuple[dict[str, float], float]:
        """pull ∈ [pull_lo, pull_hi] per circuit_key: how much pace overcomes
        grid. Derived from grid↔finish rank correlation among finishers
        (sticky track = high correlation = low pull), shrunk to the mean."""
        r = self._results
        if r.empty:
            return {}, (self.p["pull_lo"] + self.p["pull_hi"]) / 2
        fin = r[_is_finish(r["Status"])]
        key = "circuit_key" if "circuit_key" in r.columns else "event_name"

        def _stick(g: pd.DataFrame) -> float:
            if g["GridPosition"].nunique() < 4 or len(g) < 6:
                return np.nan
            rho = spearmanr(g["GridPosition"], g["Position"]).correlation
            return rho if np.isfinite(rho) else np.nan

        per = fin.groupby([key, "season", "round_number"]).apply(_stick).dropna()
        glob = float(per.mean())
        n = per.groupby(level=0).size()
        stick = per.groupby(level=0).mean()
        # shrink each circuit's stickiness toward the global mean
        k = self.p["shrink_races"]
        stick_sh = (n * stick + k * glob) / (n + k)

        def _to_pull(s: float) -> float:
            # map stickiness (higher = harder to pass) to pull (lower)
            lo, hi = self.p["pull_lo"], self.p["pull_hi"]
            # normalise stickiness across the observed range to [0,1]
            smin, smax = stick_sh.min(), stick_sh.max()
            if smax - smin < 1e-6:
                return (lo + hi) / 2
            frac = (s - smin) / (smax - smin)          # 0=least sticky
            return hi - frac * (hi - lo)               # least sticky → hi pull

        pull = {c: float(_to_pull(s)) for c, s in stick_sh.items()}
        global_pull = float(_to_pull(glob))
        return pull, global_pull

    def passability(self, event: str) -> float:
        """pull for an event name (via its circuit), global fallback."""
        ck = self._event_to_circuit.get(event)
        if ck and ck in self._pull:
            return self._pull[ck]
        # try a slugified match on circuit keys
        return self._global_pull

    # ── simulation ────────────────────────────────────────────

    def _sample_pace(self, pred: pd.DataFrame, rng: np.random.Generator,
                     n: int) -> np.ndarray:
        """(n, k) sampled pace; teammates share their car draw. Lower=faster."""
        d = pred.reset_index(drop=True)
        teams = d["team"].unique()
        car = {t: rng.standard_normal(n) * np.sqrt(
            float(d[d["team"] == t]["car_var"].iloc[0])) for t in teams}
        out = np.empty((n, len(d)))
        for i, r in d.iterrows():
            indep = rng.standard_normal(n) * np.sqrt(r["drv_var"])
            out[:, i] = r["mean"] + car[r["team"]] + indep
        return out

    def forecast(self, race_pred: pd.DataFrame, *,
                 event: str,
                 grid: dict[str, int] | None = None,
                 quali_pred: pd.DataFrame | None = None,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
        """Finishing-position distribution per driver.

        race_pred  : PaceModel.driver_predictions(kind='longrun') — needs
                     mean, car_var, drv_var per driver.
        grid       : {driver: grid_pos} actual starting order (post-quali).
        quali_pred : PaceModel.driver_predictions(kind='onelap') — used to
                     SAMPLE the grid when `grid` is None (pre-quali forecast).
        Returns driver, team, p_win, p_podium, p_points, e_finish, p_dnf.
        """
        if race_pred is None or race_pred.empty:
            return pd.DataFrame()
        rng = rng or np.random.default_rng(23)
        d = race_pred.reset_index(drop=True)
        k = len(d)
        n = self.p["n_sims"]
        drivers = d["driver"].tolist()
        pull = self.passability(event)

        pace = self._sample_pace(d, rng, n)                 # (n,k) lower=faster
        pace_rank = pace.argsort(axis=1).argsort(axis=1) + 1  # 1=fastest

        if grid is not None:
            grid_rank = np.array([[grid.get(dr, k)] for dr in drivers]).T \
                          .repeat(n, axis=0).astype(float)
        elif quali_pred is not None and not quali_pred.empty:
            qp = quali_pred.set_index("driver").reindex(drivers).reset_index()
            qp["team"] = qp["team"].fillna(d["team"])
            qp["car_var"] = qp["car_var"].fillna(d["car_var"].mean())
            qp["drv_var"] = qp["drv_var"].fillna(d["drv_var"].mean())
            qp["mean"] = qp["mean"].fillna(qp["mean"].mean())
            qpace = self._sample_pace(qp, rng, n)
            grid_rank = qpace.argsort(axis=1).argsort(axis=1) + 1.0
        else:
            grid_rank = pace_rank.astype(float)             # no grid info

        # expected running order, then race-day shuffle
        score = grid_rank + pull * (pace_rank - grid_rank)
        score = score + rng.standard_normal((n, k)) * self.p["race_noise"]

        # retirements: knock cars far back this sim
        dnf = rng.random((n, k)) < self.p["dnf_rate"]
        score = np.where(dnf, 1e6 + rng.random((n, k)), score)

        finish = score.argsort(axis=1).argsort(axis=1) + 1   # 1=win

        p_win = (finish == 1).mean(axis=0)
        p_podium = (finish <= 3).mean(axis=0)
        p_points = (finish <= 10).mean(axis=0)
        # expected finish counts DNFs as classified behind finishers
        e_finish = finish.mean(axis=0)
        p_dnf = dnf.mean(axis=0)

        return pd.DataFrame({
            "driver": drivers, "team": d["team"],
            "p_win": p_win, "p_podium": p_podium, "p_points": p_points,
            "e_finish": e_finish, "p_dnf": p_dnf,
        }).sort_values("e_finish").reset_index(drop=True)
