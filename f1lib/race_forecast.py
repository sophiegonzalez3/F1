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

Retirements are modelled at two levels, both measured rather than assumed:
the base rate is scaled by a per-CIRCUIT multiplier (0.71x Barcelona to 1.38x
Australia, a 1.9x spread over 3235 starts), and teammates' failures are
CORRELATED via a shared per-team shock, because they demonstrably are —
P(both cars out) is 3.06% against 2.02% under independence.

What this does NOT model: pit-strategy calls, weather changes mid-race, and
per-TEAM reliability differences (only per-circuit). It is a PACE-and-track
forecast, honest about that.

Deliberately NOT modelled, having been measured and found unsupported: a
per-DRIVER retirement rate (chi2 = 23.9, df = 19, p = 0.20 — indistinguishable
from binomial noise), and a per-GRID-SLOT rate. The raw grid gradient is
strong (8.6% at P1-3 rising to 17.9% at P15+) but it is CAR QUALITY, not
track position: comparing the two cars of the SAME team at the same race, the
one starting further back retires only 15.1% of the time against 13.3%
(McNemar p = 0.15). Slow cars start at the back and slow cars break.

Entry point
-----------
    from f1lib.race_forecast import RaceForecaster
    rf = RaceForecaster()
    out = rf.forecast(race_pred, quali_pred=quali_pred, event="Monaco Grand Prix")
    # out: driver, team, p_win, p_podium, p_points, e_finish, p_dnf
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr

from f1lib.circuits import circuit_id
from f1lib.pace_features import canon

logger = logging.getLogger(__name__)

HIST = Path("data/historical_results")

DEFAULTS = dict(
    n_sims=20000,
    race_noise=2.2,        # positions of race-day shuffle sd (strategy, traffic)
    # Base per-car retirement probability. MEASURED, not guessed: the
    # pre-2026 archive gives 0.133 over 2993 classified starts (0.144 before
    # 2023, 0.121 for 2023-25). It could not be measured until _is_finish was
    # fixed — while lapped finishers counted as retirements the archive
    # appeared to show a 50% retirement rate in 2026. Set to the recent-era
    # figure rather than the long pooled one, since reliability has improved;
    # the 2026 holdout runs hotter at 0.182 (new regulations), which is the
    # right kind of thing for this constant NOT to chase.
    dnf_rate=0.12,
    # Retirement risk is NOT flat across circuits. Measured over 3235
    # classified starts, the shrunk per-circuit rate runs from 0.101
    # (Barcelona) to 0.196 (Australia) around a 0.142 pooled mean — a 1.9x
    # spread, and one of the cleanest signals in the archive.
    #
    # Applied as a MULTIPLIER on dnf_rate rather than as an absolute rate, so
    # the deliberate choice of base level above (recent-era 0.12, not the
    # long-run 0.142) survives. Multipliers therefore run ~0.71 to ~1.38.
    # ── safety-car mixture (OFF by default) ───────────────────
    # `race_noise` above is drawn independently per driver, but the biggest
    # thing it stands in for — a safety car — is a RACE-LEVEL event that
    # happens to everybody at once. Independent draws therefore get the
    # marginal spread right and the JOINT behaviour wrong, understating how
    # often several cars are displaced together. Exactly the defect already
    # fixed for teammate retirements, which are correlated for the same kind
    # of reason.
    #
    # Measured over 163 races (2019-2026): a race with a safety car shuffles
    # 1.175x more than one without (sd of finish-grid, 5.24 vs 4.46,
    # Mann-Whitney p=0.0012), and 55.8% of races have one.
    #
    # Applied as a variance-PRESERVING mixture: one scale is drawn per
    # simulated race, and the two levels are set so the marginal variance
    # still equals race_noise^2. That keeps this a change of SHAPE only, so it
    # can be tested without also re-tuning the amount of noise — which is what
    # the house rule about constants exists to prevent.
    #
    # TESTED AND REJECTED as a default. Scored over 105 races, it moves
    # nothing: pooled Brier -0.0001 (p_win), +0.0000 (podium, points), every
    # 95% CI straddling zero, and seasons improved 4/6, 2/6, 3/6 — i.e. a coin
    # flip. Sharpness goes 1.237 -> 1.236. The input effect is real and well
    # measured; it is simply too gentle to survive a rank-based simulation
    # once the marginal variance is held fixed.
    #
    # Kept, off, because a measured null is worth more than a deleted branch:
    # it stops the same idea being re-proposed as free accuracy, and it is the
    # honest home for the SC constants above. Turning it on would need it to
    # clear scripts/backtest_race_forecast.py on several seasons first.
    sc_mixture=False,
    sc_rate=0.558,           # P(any safety car), 163 races
    sc_noise_mult=1.175,     # shuffle multiplier on a safety-car race
    dnf_shrink_starts=80.0,   # pseudo-starts pulling a circuit toward the mean
    # Teammates retire together more often than chance: P(both) is 3.06%
    # against 2.02% under independence over 1599 team-races (chi2 = 11.3,
    # p = 0.0008), i.e. P(B retires | A retired) = 22.6% vs 14.8%
    # unconditional, a 1.5x lift. Shared batches, shared design flaws, shared
    # first-lap incidents. Independent Bernoulli draws understate double
    # retirements by half, which biases every OTHER driver's podium and
    # points probability upward.
    #
    # Implemented as a Gaussian copula: this is the LATENT correlation that
    # reproduces the observed P(both) exactly at the measured marginals, not
    # the phi coefficient of the 2x2 (0.084), which is a different quantity.
    dnf_corr=0.19,
    pull_lo=0.20,          # passability floor (even Monaco lets a little pace through)
    pull_hi=0.85,          # ceiling (even Monza isn't a pure pace sort)
    shrink_races=8.0,      # pseudo-races pulling circuit stickiness to the mean
)

_DNF_KEYWORDS = (# "Did not start" / "Did not qualify" match no mechanical
                 # keyword, so the catch-all clause below used to wave them
                 # through as finishers. A car that never started cannot
                 # inform how hard a circuit is to overtake on.
                 "Did not",
                 "Accident", "Collision", "Spun", "Retired", "Withdrew",
                 "Disqualified", "Engine", "Gearbox", "Hydraulics",
                 "Power", "Brakes", "Suspension", "Transmission", "Electrical",
                 "Overheating", "Mechanical", "Puncture", "Wheel", "Fuel",
                 "Water", "Oil", "Clutch", "Driveshaft", "Damage", "Battery",
                 "Exhaust", "Radiator", "Vibrations", "Debris", "Steering")


def _is_finish(status: pd.Series) -> pd.Series:
    """Did the car see the flag? Lapped finishers count — they finished.

    The archive changed vocabulary in 2023: a car a lap down used to be
    "+1 Lap" and is now "Lapped". The old blanket exclusion of anything
    containing "Lap" was harmless then (the `^\\+\\d` clause caught "+1 Lap"
    first) and silently wrong afterwards — it reclassified 375 lapped
    FINISHERS as retirements from 2023 on, which is why the archive appears
    to show a 50% retirement rate in 2026. Passability is measured from
    grid-vs-finish among classified finishers, so this dropped exactly the
    backmarkers whose grid-to-finish relationship says most about how hard a
    circuit is to overtake on.
    """
    s = status.astype(str)
    return (s.str.startswith("Finished")
            | s.str.startswith("Lapped")
            | s.str.match(r"^\+\d")
            | (~s.str.contains("|".join(_DNF_KEYWORDS), case=False, na=False)
               & ~s.str.contains("Lap", na=False)))


class RaceForecaster:
    def __init__(self, **overrides):
        self.p = {**DEFAULTS, **overrides}
        self._results = self._load_results()
        self._pull, self._global_pull = self._circuit_passability()
        self._event_to_circuit = self._event_map()
        self._circuit_dnf_map = self._circuit_dnf()

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
        r = r[r["GridPosition"] > 0].copy()
        # Key every multi-season circuit statistic on circuit_id, never on the
        # archive's circuit_key (which is derived from the EVENT name). Five
        # circuits are split across two keys — Barcelona sits under both
        # `spanish_grand_prix` and `barcelona_grand_prix`, and Interlagos,
        # Mexico City, the Red Bull Ring and Silverstone likewise — so keying
        # on circuit_key silently fragments their history and hands the
        # renamed half a thin, shrunk-to-the-mean estimate. Barcelona's
        # retirement multiplier came out 1.27 under circuit_key against 0.71
        # under circuit_id: it is the SAFEST circuit in the archive and was
        # being reported as one of the harshest.
        r["circuit_id"] = [circuit_id(e, s)
                           for e, s in zip(r["event_name"], r["season"])]
        return r

    def _event_map(self) -> dict[str, str]:
        """event name -> circuit_id. Must agree with the key the per-circuit
        statistics are grouped on, or every lookup silently falls back to the
        global default."""
        if self._results.empty or "circuit_id" not in self._results.columns:
            return {}
        return (self._results.dropna(subset=["circuit_id"])
                .drop_duplicates("event_name")
                .set_index("event_name")["circuit_id"].to_dict())

    def _circuit_passability(self) -> tuple[dict[str, float], float]:
        """pull ∈ [pull_lo, pull_hi] per circuit_key: how much pace overcomes
        grid. Derived from grid↔finish rank correlation among finishers
        (sticky track = high correlation = low pull), shrunk to the mean."""
        r = self._results
        if r.empty:
            return {}, (self.p["pull_lo"] + self.p["pull_hi"]) / 2
        fin = r[_is_finish(r["Status"])]
        key = "circuit_id" if "circuit_id" in r.columns else "event_name"

        def _stick(g: pd.DataFrame) -> float:
            if g["GridPosition"].nunique() < 4 or len(g) < 6:
                return np.nan
            rho = spearmanr(g["GridPosition"], g["Position"]).correlation
            return rho if np.isfinite(rho) else np.nan

        # Select the two columns _stick needs BEFORE applying: passing the
        # whole frame makes pandas hand the grouping columns to the callable
        # too, which is deprecated (and the suite treats FutureWarning as an
        # error precisely to catch that early).
        per = (fin.groupby([key, "season", "round_number"])[
                   ["GridPosition", "Position"]]
               .apply(_stick).dropna())
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

    def _circuit_dnf(self) -> dict[str, float]:
        """Per-circuit retirement MULTIPLIER on `dnf_rate`, shrunk to 1.0.

        Measured from classified starts, not guessed. Returned as a ratio so
        the configured base rate keeps setting the level and the circuit only
        sets the shape — otherwise this would silently overwrite the
        deliberate choice of a recent-era base over the long-run pooled one.
        """
        r = self._results
        if r.empty or "Status" not in r.columns:
            return {}
        key = "circuit_id" if "circuit_id" in r.columns else "event_name"
        dnf = (~_is_finish(r["Status"])).astype(float)
        glob = float(dnf.mean())
        if not np.isfinite(glob) or glob <= 0:
            return {}
        g = dnf.groupby(r[key]).agg(["size", "mean"])
        k = self.p["dnf_shrink_starts"]
        shrunk = (g["size"] * g["mean"] + k * glob) / (g["size"] + k)
        return (shrunk / glob).to_dict()

    def dnf_multiplier(self, event: str) -> float:
        """Circuit retirement multiplier for an event name; 1.0 if unknown."""
        ck = self._event_to_circuit.get(event, event)
        return float(self._circuit_dnf_map.get(ck, 1.0))

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

    def simulate(self, race_pred: pd.DataFrame, *,
                 event: str,
                 grid: dict[str, int] | None = None,
                 quali_pred: pd.DataFrame | None = None,
                 rng: np.random.Generator | None = None,
                 dnf_rates: dict[str, float] | None = None,
                 race_noise: float | None = None) -> dict | None:
        """Run the Monte Carlo and return the raw per-sim arrays.

        Same inputs as :meth:`forecast`, plus optional per-driver retirement
        probabilities (``dnf_rates``, falling back to the flat default) and a
        ``race_noise`` override. Returns a dict of (n_sims, k) arrays —
        ``finish``, ``dnf``, ``pace_rank``, ``grid_rank`` — plus the aligned
        ``drivers`` list, so callers can compute pairwise / conditional
        statistics that the aggregated forecast table throws away.
        """
        if race_pred is None or race_pred.empty:
            return None
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
        noise = self.p["race_noise"] if race_noise is None else race_noise
        score = grid_rank + pull * (pace_rank - grid_rank)
        # One scale per SIMULATED RACE, not per driver: a safety car displaces
        # the whole field together. `base` is chosen so the marginal variance
        # is unchanged (p*m^2 + (1-p)) * base^2 = 1, making this purely a
        # change of shape. See the note on sc_mixture in DEFAULTS.
        if self.p.get("sc_mixture"):
            p_sc = float(np.clip(self.p["sc_rate"], 0.0, 1.0))
            mult = float(max(self.p["sc_noise_mult"], 1e-6))
            base = 1.0 / np.sqrt(p_sc * mult ** 2 + (1.0 - p_sc))
            scale = np.where(rng.random(n) < p_sc, base * mult, base)[:, None]
        else:
            scale = 1.0
        score = score + rng.standard_normal((n, k)) * noise * scale

        # ── retirements ───────────────────────────────────────
        # Rate: the configured base, scaled by how hard this circuit is on
        # cars (measured, 0.71x Barcelona to 1.38x Australia). An explicit
        # dnf_rates mapping overrides both.
        mult = self.dnf_multiplier(event)
        if dnf_rates is not None:
            rates = np.array([dnf_rates.get(dr, self.p["dnf_rate"] * mult)
                              for dr in drivers], dtype=float)
        else:
            rates = np.full(k, self.p["dnf_rate"] * mult, dtype=float)
        rates = np.clip(rates, 1e-6, 1 - 1e-6)

        # Correlation: teammates fail together more often than chance, so the
        # draw is a Gaussian copula with a shared per-team shock rather than
        # k independent Bernoullis. Same device as the shared car draw in
        # _sample_pace, and for the same reason — the thing being shared is
        # real (a batch, a design flaw, a first-lap incident that takes both
        # cars). Independent draws halve the odds of a double retirement.
        corr = float(np.clip(self.p.get("dnf_corr", 0.0), 0.0, 0.99))
        if corr > 0:
            shared = {t: rng.standard_normal(n) for t in set(d["team"])}
            z = np.empty((n, k))
            a, b = np.sqrt(corr), np.sqrt(1.0 - corr)
            for i, t in enumerate(d["team"]):
                z[:, i] = a * shared[t] + b * rng.standard_normal(n)
        else:
            z = rng.standard_normal((n, k))
        dnf = z < norm.ppf(rates)[None, :]
        score = np.where(dnf, 1e6 + rng.random((n, k)), score)

        finish = score.argsort(axis=1).argsort(axis=1) + 1   # 1=win
        return {"drivers": drivers, "teams": d["team"].tolist(),
                "finish": finish, "dnf": dnf,
                "pace_rank": pace_rank, "grid_rank": grid_rank,
                "pull": pull}

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
        sim = self.simulate(race_pred, event=event, grid=grid,
                            quali_pred=quali_pred, rng=rng)
        if sim is None:
            return pd.DataFrame()
        d = race_pred.reset_index(drop=True)
        drivers, finish, dnf = sim["drivers"], sim["finish"], sim["dnf"]

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
