"""Progressive weekend pace prediction.

Estimates, for every team at a given event, two latent quantities as % gaps
to the field mean: ONE-LAP pace (what qualifying will show) and LONG-RUN pace
(what the race will show). The estimate starts from an era-aware season-form
prior and is sharpened after each practice session by the measurements from
pace_features.py, in a plain Gaussian precision-weighted (Kalman-style)
update. Every number carries a variance, so the output is an ordering WITH
uncertainty, not a fake-precise ranking.

Era awareness
-------------
Formula 1 resets car competitiveness at regulation breaks. The prior only
ever looks at rounds inside the same era (2022–2025 ground-effect cars;
2026+ new engine/aero rules; 2021 and earlier its own block), weights recent
rounds more (exponential decay, HALF_LIFE_ROUNDS), and adds a pseudo-distance
at season boundaries (winter development shuffles the order even within an
era). A team with no history in the era — Cadillac in 2026, anyone at an era
opener — gets a wide, field-mean prior: the model honestly says "no idea
yet" and lets practice data speak.

Measurement model
-----------------
pace_features emits per-session team gaps centered on the mean of the teams
in that measurement set, with a standard error. The observation noise is
   se²  +  base_noise(kind, session)²
where base_noise captures how representative that session is of the real
thing (fuel/engine-mode games, programme differences) over and above lap-time
scatter. Those constants are the model's only real tuning knobs and are
validated by backtest_pace_model.py.

Main entry point
----------------
    model = PaceModel()
    stages = model.predict_weekend(2026, "Belgian Grand Prix")
    # {"prior": df, "after FP1": df, "after FP2": df, ...}
    # df columns: team, kind, mean, sd  (gap % to field mean; lower = faster)
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from pace_features import event_measurements, canon

logger = logging.getLogger(__name__)

PACE_CSV = Path("data/team_pace_by_event.csv")

DEFAULTS: dict = {
    # ── prior construction ──
    "half_life_rounds": 4.0,     # EW decay of past rounds' influence
    "season_gap_rounds": 6.0,    # extra pseudo-rounds of distance across winter
    "min_prior_var": 0.06,       # %² — form is never a perfect predictor
    "max_prior_var": 4.0,        # %² — cap so one team can't go fully diffuse
    "new_team_sd": 1.5,          # % — prior sd with no era history
    "longrun_from_onelap_var": 0.30,  # %² added when race form is missing and
                                      # the one-lap prior stands in for it
    # ── measurement noise beyond the fit SE, per (kind, session) in % ──
    # Long-run noise is deliberately high: practice race-sims run on unknown
    # fuel and engine modes with different programmes per team, so they are a
    # weak read on true race pace. Backtest (backtest_pace_model.py, 2024-25)
    # confirmed lower long-run noise makes practice DRIFT WORSE than the
    # season-form prior in the settled era. One-lap sims are far more
    # representative and get more trust as the weekend sharpens.
    # Sprint Qualifying is a real low-fuel qualifying (better than any practice
    # sim) and the Sprint is a real race on race fuel (the strongest long-run
    # read there is) — both get low noise, the Sprint the lowest of any
    # long-run source.
    "base_noise": {
        ("onelap", "Practice 1"): 0.55,
        ("onelap", "Practice 2"): 0.35,
        ("onelap", "Practice 3"): 0.25,
        ("onelap", "Sprint Qualifying"): 0.20,
        ("longrun", "Practice 1"): 0.85,
        ("longrun", "Practice 2"): 0.70,
        ("longrun", "Practice 3"): 0.85,
        ("longrun", "Sprint"): 0.45,
    },
    "default_base_noise": 0.6,
    # ── outcome simulation ──
    "exec_sd": 0.18,             # % — event-day execution noise per team
    "n_sims": 20000,
}

# Weekend order of the pre-outcome sessions the model can ingest. A normal
# weekend has the three practices; a sprint weekend has FP1 then Sprint
# Qualifying and the Sprint (which run before qualifying and the race, so
# using them to predict those is legitimate). Missing sessions are skipped.
_SESSION_ORDER = ["Practice 1", "Practice 2", "Practice 3",
                  "Sprint Qualifying", "Sprint"]

# short stage labels for snapshots
_STAGE_LABEL = {"Practice 1": "FP1", "Practice 2": "FP2", "Practice 3": "FP3",
                "Sprint Qualifying": "SprintQuali", "Sprint": "Sprint"}

# kind of the model (team) latent → kind of driver effect that refines it
_DRIVER_KIND = {"onelap": "quali", "longrun": "race"}


def era_of(season: int) -> str:
    if season >= 2026:
        return "2026-regs"
    if season >= 2022:
        return "ground-effect"
    return "pre-2022"


class PaceModel:
    def __init__(self, pace_csv: str | Path = PACE_CSV, **overrides):
        self.p = {**DEFAULTS, **overrides}
        self._driver_ratings = None            # lazy (needs driver_pace CSV)
        df = pd.read_csv(pace_csv)
        df["team"] = df["team"].map(canon)
        df["era"] = df["season"].map(era_of)
        # global chronological event index within era (for cross-season decay)
        df = df.sort_values(["season", "round"])
        key = df.drop_duplicates(["season", "round"])[["season", "round"]]
        key = key.reset_index(drop=True)
        key["event_idx"] = range(len(key))
        self.pace = df.merge(key, on=["season", "round"])
        self._round_of = {(int(r["season"]), str(r["event"])): int(r["round"])
                          for _, r in
                          df.drop_duplicates(["season", "event"]).iterrows()}

    # ── helpers ───────────────────────────────────────────────

    def round_of(self, season: int, event: str) -> int | None:
        return self._round_of.get((int(season), str(event)))

    def teams_of_season(self, season: int) -> list[str]:
        return sorted(self.pace[self.pace["season"] == season]["team"].unique())

    def _centered_history(self, season: int, round_: int,
                          col: str) -> pd.DataFrame:
        """Past rounds in the same era, strictly before (season, round), with
        the gap column centered per round and a distance in pseudo-rounds."""
        e = era_of(season)
        h = self.pace[(self.pace["era"] == e) & self.pace[col].notna()].copy()
        h = h[(h["season"] < season)
              | ((h["season"] == season) & (h["round"] < round_))]
        if h.empty:
            return h
        h["gap_c"] = h[col] - h.groupby(["season", "round"])[col].transform("mean")
        # distance = events back + winter penalty per season boundary
        cur_idx_rows = self.pace[(self.pace["season"] == season)
                                 & (self.pace["round"] == round_)]
        if cur_idx_rows.empty:
            cur_idx = self.pace[self.pace["era"] == e]["event_idx"].max() + 1
        else:
            cur_idx = cur_idx_rows["event_idx"].iloc[0]
        h["dist"] = (cur_idx - h["event_idx"]).astype(float) \
            + (season - h["season"]) * self.p["season_gap_rounds"]
        return h

    def _prior_kind(self, season: int, round_: int, col: str,
                    teams: list[str]) -> pd.DataFrame:
        """EW form prior for one gap column. Teams without history get a
        wide field-mean prior."""
        h = self._centered_history(season, round_, col)
        rows = []
        for team in teams:
            g = h[h["team"] == team] if not h.empty else pd.DataFrame()
            if g.empty:
                rows.append({"team": team, "mean": 0.0,
                             "var": self.p["new_team_sd"] ** 2, "n_eff": 0.0})
                continue
            w = 0.5 ** (g["dist"] / self.p["half_life_rounds"])
            mean = float(np.average(g["gap_c"], weights=w))
            n_eff = float(w.sum() ** 2 / (w ** 2).sum())
            if n_eff > 1.5:
                resid_var = float(np.average((g["gap_c"] - mean) ** 2, weights=w))
                var = resid_var / n_eff
            else:
                var = self.p["new_team_sd"] ** 2 / 2
            var = float(np.clip(var + self.p["min_prior_var"],
                                self.p["min_prior_var"], self.p["max_prior_var"]))
            rows.append({"team": team, "mean": mean, "var": var, "n_eff": n_eff})
        out = pd.DataFrame(rows)
        out["mean"] -= out["mean"].mean()      # keep the field mean at zero
        return out

    def prior(self, season: int, round_: int,
              teams: list[str] | None = None) -> pd.DataFrame:
        """Pre-weekend prior. Columns: team, kind, mean, var."""
        teams = teams or self.teams_of_season(season)
        one = self._prior_kind(season, round_, "quali_gap_pct", teams)
        lng = self._prior_kind(season, round_, "race_pace_gap_pct", teams)
        # race-pace history only exists for locally-cached rounds; where it is
        # too thin, the one-lap form is the best available stand-in (they are
        # strongly correlated), with honesty about the extra uncertainty
        thin = lng["n_eff"] < 2.0
        if thin.any():
            fallback = one.set_index("team")
            for i in lng[thin].index:
                t = lng.loc[i, "team"]
                lng.loc[i, "mean"] = fallback.loc[t, "mean"]
                lng.loc[i, "var"] = min(
                    fallback.loc[t, "var"] + self.p["longrun_from_onelap_var"],
                    self.p["max_prior_var"])
            lng["mean"] -= lng["mean"].mean()
        one["kind"], lng["kind"] = "onelap", "longrun"
        cols = ["team", "kind", "mean", "var"]
        return pd.concat([one[cols], lng[cols]], ignore_index=True)

    # ── measurement update ────────────────────────────────────

    def _update_with_set(self, state: pd.DataFrame,
                         mset: pd.DataFrame) -> pd.DataFrame:
        """Precision-weighted update of `state` (team,kind,mean,var) with one
        measurement set (single kind+session, gaps centered within the set).

        The set's gaps are relative to the mean of ITS teams, not the whole
        field; re-anchor them using the current state means of those same
        teams so partial coverage can't shift the field.
        """
        state = state.copy().set_index(["team", "kind"])
        kind = mset["kind"].iloc[0]
        session = mset["session"].iloc[0]
        noise = self.p["base_noise"].get((kind, session),
                                         self.p["default_base_noise"])
        idx = [(t, kind) for t in mset["team"]]
        known = [i for i in idx if i in state.index]
        if not known:
            return state.reset_index()
        anchor = float(np.mean([state.loc[i, "mean"] for i in known]))
        for _, m in mset.iterrows():
            key = (m["team"], kind)
            if key not in state.index:
                # a team we have no state for (shouldn't happen mid-season)
                state.loc[key, ["mean", "var"]] = (
                    m["gap_pct"] + anchor,
                    m["se_pct"] ** 2 + noise ** 2)
                continue
            y = m["gap_pct"] + anchor
            r = m["se_pct"] ** 2 + noise ** 2
            mu, v = state.loc[key, "mean"], state.loc[key, "var"]
            k = v / (v + r)
            state.loc[key, "mean"] = mu + k * (y - mu)
            state.loc[key, "var"] = v * (1 - k)
        return state.reset_index()

    def update(self, state: pd.DataFrame,
               measurements: pd.DataFrame) -> pd.DataFrame:
        """Apply every measurement set in `measurements` (possibly several
        sessions × kinds) to the state, in session order."""
        if measurements is None or measurements.empty:
            return state
        for session in _SESSION_ORDER:
            for kind in ("onelap", "longrun"):
                mset = measurements[(measurements["session"] == session)
                                    & (measurements["kind"] == kind)]
                if not mset.empty:
                    state = self._update_with_set(state, mset)
        return state

    # ── weekend driver ────────────────────────────────────────

    def predict_weekend(self, season: int, event: str,
                        measurements: pd.DataFrame | None = None,
                        round_: int | None = None) -> dict[str, pd.DataFrame]:
        """Stage-by-stage predictions for one event.

        measurements: pre-extracted team measurements (pace_features format);
        fetched from the session caches when omitted. Returns an ordered dict
        stage-name → state df (team, kind, mean, var, sd).
        """
        round_ = round_ if round_ is not None else self.round_of(season, event)
        if round_ is None:
            raise ValueError(f"event not in pace table: {season} {event} — "
                             "run compute_team_pace.py for that season")
        if measurements is None:
            measurements, _ = event_measurements(season, event)

        teams = self.teams_of_season(season)
        if measurements is not None and not measurements.empty:
            teams = sorted(set(teams) | set(measurements["team"]))
        state = self.prior(season, round_, teams)

        stages: dict[str, pd.DataFrame] = {}

        def _snap(name: str, st: pd.DataFrame):
            out = st.copy()
            out["sd"] = np.sqrt(out["var"])
            stages[name] = out

        _snap("prior", state)
        if measurements is not None and not measurements.empty:
            for session in _SESSION_ORDER:
                msess = measurements[measurements["session"] == session]
                if msess.empty:
                    continue
                state = self.update(state, msess)
                _snap(f"after {_STAGE_LABEL.get(session, session)}", state)
        return stages

    # ── live outcome (for the prediction ledger) ──────────────

    @staticmethod
    def actual_quali_gap(laps: pd.DataFrame) -> pd.Series:
        """Per-team qualifying gap to the field MEAN (%), from a loaded
        Qualifying session's laps. Matches the onelap prediction's units so
        the ledger can subtract them. Empty if no qualifying laps present."""
        if laps is None or laps.empty or "session" not in laps.columns:
            return pd.Series(dtype=float)
        q = laps[laps["session"].isin(["Qualifying", "Sprint Qualifying"])
                 & laps.get("ValidLap", False)]
        if q.empty:
            return pd.Series(dtype=float)
        best = q.groupby(q["Team"].map(canon))["LapTime_s"].min().dropna()
        if len(best) < 4:
            return pd.Series(dtype=float)
        return 100.0 * (best / best.mean() - 1)

    @staticmethod
    def actual_driver_race_gap(laps: pd.DataFrame) -> pd.Series:
        """Per-DRIVER race-pace gap to the field mean (%), from a loaded Race
        session — each driver's median clean-air corrected lap. Indexed by
        Driver_Short. Empty when no race laps are present."""
        if laps is None or laps.empty or "session" not in laps.columns:
            return pd.Series(dtype=float)
        r = laps[(laps["session"] == "Race") & laps.get("ValidLap", False)]
        if "Dirty_Air" in r.columns:
            r = r[~r["Dirty_Air"].fillna(False)]
        y = ("LapTime_TrackCorrected" if "LapTime_TrackCorrected" in r.columns
             else "LapTime_FuelCorrected")
        if r.empty or y not in r.columns:
            return pd.Series(dtype=float)
        med = r.groupby("Driver_Short")[y].median()
        cnt = r.groupby("Driver_Short")[y].count()
        med = med[cnt >= 10].dropna()
        if len(med) < 4:
            return pd.Series(dtype=float)
        return 100.0 * (med / med.mean() - 1)

    @staticmethod
    def actual_race_gap(laps: pd.DataFrame) -> pd.Series:
        """Per-team race-pace gap to the field MEAN (%), from a loaded Race
        session — best driver's median clean-air corrected lap. Empty when no
        race laps are present."""
        if laps is None or laps.empty or "session" not in laps.columns:
            return pd.Series(dtype=float)
        r = laps[(laps["session"] == "Race") & laps.get("ValidLap", False)]
        if "Dirty_Air" in r.columns:
            r = r[~r["Dirty_Air"].fillna(False)]
        y = ("LapTime_TrackCorrected" if "LapTime_TrackCorrected" in r.columns
             else "LapTime_FuelCorrected")
        if r.empty or y not in r.columns:
            return pd.Series(dtype=float)
        med = r.groupby([r["Team"].map(canon), "Driver_Short"])[y].median()
        cnt = r.groupby([r["Team"].map(canon), "Driver_Short"])[y].count()
        med = med[cnt >= 10]
        if med.empty:
            return pd.Series(dtype=float)
        team_best = med.groupby(level=0).min().dropna()
        if len(team_best) < 4:
            return pd.Series(dtype=float)
        return 100.0 * (team_best / team_best.mean() - 1)

    # ── driver layer ──────────────────────────────────────────

    @property
    def driver_ratings(self):
        """Lazy DriverRatings (teammate-relative driver effects). None if the
        driver_pace table hasn't been built."""
        if self._driver_ratings is None:
            try:
                from driver_ratings import DriverRatings
                self._driver_ratings = DriverRatings()
            except Exception as exc:
                logger.warning("driver ratings unavailable: %s", exc)
                self._driver_ratings = False
        return self._driver_ratings or None

    def driver_predictions(self, state: pd.DataFrame, roster: pd.DataFrame,
                           kind: str, as_of: tuple[int, int] | None = None
                           ) -> pd.DataFrame:
        """Expand a team latent into per-driver predictions.

        roster: DataFrame with columns driver, team (the entrants this event).
        The car level is inferred so the team's FASTEST driver reproduces the
        team prediction (which is best-driver anchored): car_level =
        team_mean - min(effect over the team's drivers). Each driver then sits
        at car_level + their own effect. Variance combines the team's own
        uncertainty with the driver-effect standard error.

        Returns: driver, team, mean, sd, effect, car_var, drv_var. Empty if
        driver ratings are unavailable.
        """
        dr = self.driver_ratings
        if dr is None or roster is None or roster.empty:
            return pd.DataFrame()
        eff = dr.effects(_DRIVER_KIND[kind], as_of=as_of)
        emap = eff.set_index("driver")["effect"].to_dict()
        smap = eff.set_index("driver")["se"].to_dict()
        # default for an unrated driver (rookie): average skill, wide sd
        default_se = float(eff["se"].max()) if not eff.empty else 0.4
        st = state[state["kind"] == kind].set_index("team")
        roster = roster.copy()
        roster["team"] = roster["team"].map(canon)
        roster = roster[roster["team"].isin(st.index)]
        roster["effect"] = roster["driver"].map(emap).fillna(0.0)
        roster["eff_se"] = roster["driver"].map(smap).fillna(default_se)
        rows = []
        for team, g in roster.groupby("team"):
            team_mean = float(st.loc[team, "mean"])
            team_var = float(st.loc[team, "var"])
            car_level = team_mean - g["effect"].min()   # best driver = team
            for _, r in g.iterrows():
                rows.append({
                    "driver": r["driver"], "team": team, "kind": kind,
                    "mean": car_level + r["effect"], "effect": r["effect"],
                    "car_var": team_var, "drv_var": r["eff_se"] ** 2,
                    "sd": float(np.sqrt(team_var + r["eff_se"] ** 2))})
        out = pd.DataFrame(rows)
        # re-center on the field mean so driver gaps stay comparable to team gaps
        if not out.empty:
            out["mean"] -= out["mean"].mean()
        return out.sort_values("mean").reset_index(drop=True)

    def driver_outcome_probs(self, driver_pred: pd.DataFrame,
                             rng: np.random.Generator | None = None
                             ) -> pd.DataFrame:
        """Per-driver P(fastest) and P(top-3) by Monte Carlo. Teammates SHARE
        their car's draw (a good car lifts both drivers together), then differ
        by an independent driver-effect draw plus event-day execution noise.
        This correlation is why teammates' probabilities aren't independent.
        """
        if driver_pred is None or driver_pred.empty:
            return pd.DataFrame()
        rng = rng or np.random.default_rng(11)
        d = driver_pred.reset_index(drop=True)
        n = self.p["n_sims"]
        # shared car shock per team
        teams = d["team"].unique()
        tvar = {t: float(d[d["team"] == t]["car_var"].iloc[0]) for t in teams}
        car_shock = {t: rng.standard_normal(n) * np.sqrt(tvar[t]) for t in teams}
        draws = np.empty((n, len(d)))
        exec_var = self.p["exec_sd"] ** 2
        for i, r in d.iterrows():
            indep = rng.standard_normal(n) * np.sqrt(r["drv_var"] + exec_var)
            draws[:, i] = r["mean"] + car_shock[r["team"]] + indep
        order = np.argsort(draws, axis=1)
        p_best = np.bincount(order[:, 0], minlength=len(d)) / n
        top3 = np.zeros(len(d))
        for c in range(3):
            top3 += np.bincount(order[:, c], minlength=len(d))
        out = d[["driver", "team", "kind", "mean", "sd"]].copy()
        out["p_best"] = p_best
        out["p_top3"] = top3 / n
        return out.sort_values("p_best", ascending=False).reset_index(drop=True)

    # ── outcome probabilities ─────────────────────────────────

    def outcome_probs(self, state: pd.DataFrame, kind: str = "onelap",
                      rng: np.random.Generator | None = None) -> pd.DataFrame:
        """Monte-Carlo P(fastest team) and P(top-3 team) for one kind.
        Samples each team's latent plus event-day execution noise."""
        rng = rng or np.random.default_rng(7)
        s = state[state["kind"] == kind].reset_index(drop=True)
        if s.empty:
            return pd.DataFrame()
        n = self.p["n_sims"]
        draws = (rng.standard_normal((n, len(s)))
                 * np.sqrt(s["var"].values + self.p["exec_sd"] ** 2)
                 + s["mean"].values)
        order = np.argsort(draws, axis=1)
        p_best = np.bincount(order[:, 0], minlength=len(s)) / n
        top3 = np.zeros(len(s))
        for c in range(3):
            top3 += np.bincount(order[:, c], minlength=len(s))
        return pd.DataFrame({
            "team": s["team"], "kind": kind,
            "mean": s["mean"], "sd": np.sqrt(s["var"]),
            "p_best": p_best, "p_top3": top3 / n,
        }).sort_values("p_best", ascending=False).reset_index(drop=True)
