"""Teammate-relative driver ratings (race and one-lap speed).

The team model in pace_model.py predicts how fast a CAR will be. This module
adds the missing half: how much a DRIVER adds to or subtracts from their car.
The only clean way to separate the two is teammate contrast — teammates share
a car, so any repeatable pace difference between them is the driver. Do that
across every event and the individual contrasts chain into one field-wide
scale (drivers change teams, linking everyone).

Method — one fixed-effects regression per kind
----------------------------------------------
    pace_gap[event, driver]  ~  C(season, event, team)  +  C(driver)

The (season, event, team) dummy is "this exact car on this exact weekend", so
it absorbs car pace, track and conditions. The driver dummy left over is the
driver effect, in % of lap time (negative = faster than an average driver).
Solved by ridge-stabilised least squares; the diagonal of the covariance
gives each driver a standard error, so a driver with two races is known to be
less certain than one with sixty.

Era handling — deliberately different from team pace
---------------------------------------------------
Team competitiveness resets at regulation breaks, so pace_model's team prior
never looks across an era boundary. Driver SKILL does not reset — a fast
driver stays fast when the cars change — so driver effects are fitted across
ALL available seasons, with an exponential recency weight (older events count
less) rather than an era cutoff. This is the whole reason a driver layer is
worth having for a new-regulation season: the cars are unknowns, but the
drivers are largely the same known quantities.

Data sources
------------
  quali  best of Q1/Q2/Q3 per driver, from the results archive — every round
         of every cached season, full grid.
  race   each driver's median clean-air, fuel- & track-evolution-corrected
         race lap, from cached race laps (the same measure compute_team_pace
         uses for teams) — richer per driver but only for cached races.

`build_pace_table()` writes data/driver_pace_by_event.csv (the per-event
input); `DriverRatings` fits and serves the effects.

Usage
-----
    python -m f1lib.driver_ratings      # (re)build the per-event table
                                        # (as a MODULE from the repo root —
                                        #  running the file by path leaves the
                                        #  root off sys.path and the f1lib
                                        #  imports below fail)
    from f1lib.driver_ratings import DriverRatings
    dr = DriverRatings()
    eff = dr.effects("race", as_of=(2026, 8))   # driver, effect, se, n_events
"""
from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import f1lib.data_loader as dl
from f1lib.pace_features import canon
from f1lib.quali_norm import n_sessions, normalised_gap_pct
from f1lib.config import SESSIONS_LITE_DIR
from f1lib.processing import (
    clean_and_enrich_laps, flag_dirty_air, flag_perturbed_laps,
    enrich_track_evolution,
)

logger = logging.getLogger(__name__)

PACE_TABLE = Path("data/driver_pace_by_event.csv")
HIST = Path("data/historical_results")

HALF_LIFE_EVENTS = 30.0   # recency weight: events this far back count half
MIN_EVENTS = 2            # drivers with fewer events are still fitted but flagged
RIDGE = 2.0               # shrinks thin driver effects toward 0 (one-off drivers)
# Input clip: a driver this far SLOWER THAN THEIR OWN CAR's average that
# weekend is almost never showing pace (a scrappy lap, a wet Q1, a crash, a
# lapped-car median) — it is a session event, and teammate contrast is what
# the rating is made of, so cap it.
#
# Measured WITHIN the car-event, not against the field. That is what the
# rule always meant, but it used to be applied to the absolute gap, which
# silently did something else: against a pole anchor a backmarker sat +3.5%
# on pure CAR pace, so the old quali cap discarded 14% of rows, most of them
# perfectly good laps from slow cars, and took their teammate contrasts with
# them. Within-car deviation is invariant to the baseline, so this survives
# the switch to a field-median reference. 1.5 sits at the 99th percentile of
# real teammate deviations (median 0.19, p90 0.57), dropping ~1%.
MAX_TEAMMATE_DEV = {"race": 1.5, "quali": 1.5}    # %
_HUBER_K = 1.8            # robust reweight threshold, in residual MADs


# ─────────────────────────────────────────────────────────────
# Per-event pace table
# ─────────────────────────────────────────────────────────────

def _quali_driver_gaps() -> pd.DataFrame:
    """Session-normalised best qualifying lap per driver, as % vs the field
    median (negative = faster than the median car).

    Why normalised and not the raw gap to pole (audit finding 09): the rating
    is built ENTIRELY on teammate contrast, and 31% of teammate pairs set
    their two best laps in different Q-sessions. Q3 runs on the most-rubbered
    track of the weekend and Q1 on the greenest — worth around a percent a
    session, which is larger than the driver effects being measured. A pair
    split Q1-vs-Q3 therefore carried the whole track-evolution offset inside
    the contrast, and it was booked as driver skill.

    The pole anchor was the smaller half of the problem: the car-event dummy
    in the fit absorbs any per-event additive shift, so a moving baseline
    mostly cancels there. What did NOT cancel is the evolution, because it
    falls between the teammates rather than on the car. Both are fixed here
    by reusing the team layer's corrector (f1lib.quali_norm) at driver level.
    """
    q = pd.read_parquet(HIST / "quali_results_all.parquet")
    q["best"] = q[["Q1", "Q2", "Q3"]].min(axis=1)
    q = q.dropna(subset=["best"])
    q["team"] = q["TeamName"].map(canon)
    q["driver"] = q["Abbreviation"]
    rows = []
    n_norm = n_tot = 0
    for (season, rnd, event), g in q.groupby(
            ["season", "round_number", "event_name"]):
        n_tot += 1
        # one row per driver already, so no reduction within a session
        gaps = normalised_gap_pct(g, entity="driver", reducer="min")
        if gaps:
            n_norm += 1
        else:
            # Fall back to the raw best re-centred on the field median — still
            # better than a pole anchor, just without the session correction.
            med = float(g["best"].median())
            gaps = {r["driver"]: round((r["best"] / med - 1) * 100, 3)
                    for _, r in g.iterrows()}
        nsess = n_sessions(g, "driver")
        for _, r in g.iterrows():
            gap = gaps.get(r["driver"])
            if gap is None:
                continue
            rows.append({"season": int(season), "round": int(rnd),
                         "event": event, "team": r["team"],
                         "driver": r["driver"], "kind": "quali",
                         "gap_pct": gap,
                         "n_sessions": nsess.get(r["driver"], 0)})
    logger.info("quali driver gaps: session-normalised at %d/%d rounds",
                n_norm, n_tot)
    return pd.DataFrame(rows)


def _race_driver_gaps() -> pd.DataFrame:
    """Median clean-air corrected race lap per driver as % vs the event's
    field median. Only cached races contribute.

    Reads the laps-only backfill store as well as the app's full cache. The
    full cache stops at 2023 because it carries telemetry and was never
    going to hold whole seasons, so without this the driver ratings simply
    had no race evidence before then — the same blind spot the team pace
    table had.
    """
    rows = []
    seen: set[str] = set()
    metas = []
    for base in (Path(dl.SESSIONS_DIR), Path(SESSIONS_LITE_DIR)):
        for p in sorted(Path(base).glob("*__Race__laps.parquet")):
            if p.name in seen:
                continue        # the full cache wins for the same event
            seen.add(p.name)
            metas.append(p)
    for p in metas:
        key = p.name.replace("__laps.parquet", "")
        season_s, event_s, _ = key.split("__", 2)
        # Race-control messages, when the session has them. Without these
        # flag_perturbed_laps sees only the per-lap TrackStatus column and
        # misses SHORT SECTOR YELLOWS, leaving slow laps in the median that
        # this rating is built from. compute_team_pace.py has always passed
        # them and this did not, so the driver layer and the team layer were
        # cleaning race laps to different standards off the same files.
        rcm = None
        rcm_path = p.parent / f"{key}__race_control.parquet"
        if rcm_path.exists():
            try:
                rcm = pd.read_parquet(rcm_path)
            except Exception as exc:
                logger.warning("race control unreadable for %s: %s", key, exc)
        try:
            fl = clean_and_enrich_laps(pd.read_parquet(p))
            # ORDER MATTERS — flag_perturbed_laps before enrich_track_evolution,
            # or the evolution fit runs on safety-car laps. See the same note in
            # scripts/compute_team_pace.py.
            fl = enrich_track_evolution(
                flag_dirty_air(flag_perturbed_laps(fl, rcm=rcm)))
        except Exception as exc:
            logger.warning("race pipeline failed for %s: %s", key, exc)
            continue
        y = ("LapTime_TrackCorrected" if "LapTime_TrackCorrected" in fl.columns
             else "LapTime_FuelCorrected")
        clean = fl[fl["ValidLap"]
                   & ~fl.get("Dirty_Air", False)
                   & ~fl.get("Perturbed_Lap", False)]
        med = clean.groupby(["Team", "Driver_Short"])[y].median()
        n = clean.groupby(["Team", "Driver_Short"])[y].count()
        med = med[n >= 10]
        if len(med) < 4:
            continue
        # Field MEDIAN, not the fastest driver: the minimum of noisy estimates
        # is itself noisy, so anchoring on it lets one driver's good race move
        # the scale for everyone. Matches the quali kind and the team table.
        ref = float(med.median())
        season = int(fl["season"].iloc[0]) if "season" in fl.columns \
            else int(season_s)
        event = fl["meeting"].iloc[0] if "meeting" in fl.columns \
            else event_s.replace("_", " ")
        for (team, drv), t in med.items():
            rows.append({"season": season, "round": np.nan, "event": event,
                         "team": canon(team), "driver": drv, "kind": "race",
                         "gap_pct": round((t / ref - 1) * 100, 3)})
        print(f"  [race] {season} {event}: {len(med)} drivers", flush=True)
    return pd.DataFrame(rows)


def build_pace_table() -> pd.DataFrame:
    q = _quali_driver_gaps()
    r = _race_driver_gaps()
    out = pd.concat([q, r], ignore_index=True)
    # attach the round number to race rows from the quali table (same event)
    rnd = (q.drop_duplicates(["season", "event"])
           .set_index(["season", "event"])["round"])
    miss = out["round"].isna()
    out.loc[miss, "round"] = out.loc[miss].apply(
        lambda x: rnd.get((x["season"], x["event"]), np.nan), axis=1)
    out.to_csv(PACE_TABLE, index=False)
    print(f"\nWrote {len(out)} rows -> {PACE_TABLE} "
          f"({(out['kind']=='race').sum()} race, {(out['kind']=='quali').sum()} quali)")
    return out


# ─────────────────────────────────────────────────────────────
# Fixed-effects rating fit
# ─────────────────────────────────────────────────────────────

class DriverRatings:
    def __init__(self, pace_table: str | Path = PACE_TABLE):
        df = pd.read_csv(pace_table)
        df = df.sort_values(["season", "round"])
        key = df.drop_duplicates(["season", "round"])[["season", "round"]] \
                .reset_index(drop=True)
        key["event_idx"] = range(len(key))
        self.pace = df.merge(key, on=["season", "round"], how="left")
        self._max_idx = self.pace["event_idx"].max()

    def _fit(self, sub: pd.DataFrame, as_of_idx: float,
             kind: str | None = None) -> pd.DataFrame:
        """Weighted ridge FE fit on `sub`; returns driver, effect, se, n.
        Robustified with one Huber reweight pass so a single blown lap or a
        wet Q1 can't dominate a driver's rating."""
        sub = sub.dropna(subset=["gap_pct"]).copy()
        cap = MAX_TEAMMATE_DEV.get(kind or (sub["kind"].iloc[0] if not sub.empty
                                            else "race"), 1.5)
        # a car-event with only one driver present contributes nothing to
        # teammate contrast and only adds an unidentified car dummy
        car_key = (sub["season"].astype(str) + "|" + sub["event"].astype(str)
                   + "|" + sub["team"].astype(str))
        sub = sub[car_key.groupby(car_key).transform("size") >= 2]
        if sub.empty:
            return pd.DataFrame(columns=["driver", "effect", "se", "n_events"])
        # Clip against the driver's OWN car that weekend, so a slow car is
        # never mistaken for a bad session (see MAX_TEAMMATE_DEV). Re-derive
        # the key after the size filter so the groups line up.
        car_key = (sub["season"].astype(str) + "|" + sub["event"].astype(str)
                   + "|" + sub["team"].astype(str))
        dev = sub["gap_pct"] - sub.groupby(car_key)["gap_pct"].transform("mean")
        sub = sub[dev <= cap]
        # dropping a car's slow row can leave it a single driver — re-filter
        car_key = (sub["season"].astype(str) + "|" + sub["event"].astype(str)
                   + "|" + sub["team"].astype(str))
        sub = sub[car_key.groupby(car_key).transform("size") >= 2]
        if sub.empty or sub["driver"].nunique() < 2:
            return pd.DataFrame(columns=["driver", "effect", "se", "n_events"])
        w = 0.5 ** ((as_of_idx - sub["event_idx"]).clip(lower=0)
                    / HALF_LIFE_EVENTS)
        car = pd.get_dummies(
            sub["season"].astype(str) + "|" + sub["event"].astype(str)
            + "|" + sub["team"].astype(str), prefix="car")
        drv = pd.get_dummies(sub["driver"], prefix="d")
        X = pd.concat([car, drv], axis=1).astype(float)
        cols = list(X.columns)
        Xv = X.values
        y = sub["gap_pct"].values
        lam = np.array([RIDGE if c.startswith("d_") else 0.0 for c in cols])

        def _solve(W):
            XtWX = Xv.T @ (W[:, None] * Xv) + np.diag(lam)
            try:
                inv = np.linalg.inv(XtWX)
            except np.linalg.LinAlgError:
                inv = np.linalg.pinv(XtWX)
            beta = inv @ (Xv.T @ (W * y))
            return beta, inv

        W = w.values
        beta, inv = _solve(W)
        resid = y - Xv @ beta
        # Huber reweight: shrink the influence of laps far from the fit
        mad = 1.4826 * np.median(np.abs(resid - np.median(resid)))
        if mad > 1e-6:
            r = np.abs(resid) / (_HUBER_K * mad)
            W = W * np.where(r <= 1, 1.0, 1.0 / r)
            beta, inv = _solve(W)
            resid = y - Xv @ beta
        # dof from the number of OBSERVATIONS minus parameters (not the summed
        # recency weights — those are far smaller than the car-dummy count and
        # would collapse dof, exploding s2). s2 is the weighted mean square
        # error normalised by the mean weight so it stays a proper variance.
        dof = max(len(y) - np.linalg.matrix_rank(Xv), 1.0)
        s2 = float((W * resid**2).sum() / (W.mean() * dof))
        var = np.clip(np.diag(inv) * s2, 0.0, None)
        d_idx = [i for i, c in enumerate(cols) if c.startswith("d_")]
        eff = pd.DataFrame({
            "driver": [cols[i][2:] for i in d_idx],
            "effect": [beta[i] for i in d_idx],
            "se": [np.sqrt(var[i]) for i in d_idx],
        })
        n_ev = sub.groupby("driver")["event_idx"].nunique()
        eff["n_events"] = eff["driver"].map(n_ev).fillna(0).astype(int)
        # center effects on the (recency-weighted) field mean so 0 = average
        eff["effect"] -= np.average(eff["effect"])
        return eff.sort_values("effect").reset_index(drop=True)

    def effects(self, kind: str, as_of: tuple[int, int] | None = None
                ) -> pd.DataFrame:
        """Driver effects for `kind` ('race'|'quali') using events strictly
        before as_of=(season, round). Without as_of, uses everything."""
        sub = self.pace[self.pace["kind"] == kind]
        if as_of is not None:
            season, rnd = as_of
            sub = sub[(sub["season"] < season)
                      | ((sub["season"] == season) & (sub["round"] < rnd))]
            as_of_idx = self._as_of_idx(season, rnd)
        else:
            as_of_idx = self._max_idx
        return self._fit(sub, as_of_idx, kind=kind)

    def roster(self, season: int, event: str) -> pd.DataFrame:
        """driver, team entrants for one event, from the pace table. Prefers
        the race rows (actual race entrants); falls back to quali."""
        s = self.pace[(self.pace["season"] == season)
                      & (self.pace["event"] == event)]
        for kind in ("race", "quali"):
            r = s[s["kind"] == kind][["driver", "team"]].drop_duplicates()
            if not r.empty:
                return r.reset_index(drop=True)
        return pd.DataFrame(columns=["driver", "team"])

    def _as_of_idx(self, season: int, rnd: int) -> float:
        prior = self.pace[(self.pace["season"] < season)
                          | ((self.pace["season"] == season)
                             & (self.pace["round"] <= rnd))]
        return prior["event_idx"].max() if not prior.empty else 0.0


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    build_pace_table()
    dr = DriverRatings()
    for kind in ("race", "quali"):
        eff = dr.effects(kind)
        print(f"\n=== {kind} driver effects (all history, % of lap) ===")
        print(eff.head(6).round(3).to_string(index=False))
        print("  …")
        print(eff.tail(4).round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
