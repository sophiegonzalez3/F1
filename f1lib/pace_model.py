"""Progressive weekend pace prediction.

Estimates, for every team at a given event, two latent quantities as % gaps
to the field mean: ONE-LAP SPEED (what qualifying will show) and LONG-RUN pace
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

from f1lib.config import (
    apply_pace_legacy_columns, SESSIONS_DIR, SESSIONS_LITE_DIR,
)
from f1lib.pace_features import event_measurements, canon

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
    # RE-TUNED 2026-08 against the session-normalised target (the switch from
    # gap-to-pole). Outcome: KEEP THESE VALUES. The grid search on 2024 either
    # reproduced them or moved one step on thin data, and the tuned set scored
    # slightly WORSE on the 2025 validation season and identically on the 2026
    # holdout. Two things the run exposed, both now guarded in tune():
    #   * the long-run constants are UNIDENTIFIABLE on 2024 — it has 2 / 1 / 0
    #     events at FP1 / FP2 / FP3, so the score is byte-identical for every
    #     candidate and the search returns whichever it tried first. The 0.35
    #     it "found" for longrun FP3 was fitted on nothing.
    #   * one-lap FP1 is FLAT: sweeping 0.40 → 1.00 moves the score by 0.002.
    #     Its exact value barely matters, so there is nothing to gain here.
    # Long-run noise is deliberately high: practice race-sims run on unknown
    # fuel and engine modes with different programmes per team, so they are a
    # weak read on true race pace. Backtest (backtest_pace_model.py, 2024-25)
    # confirmed lower long-run noise makes practice DRIFT WORSE than the
    # season-form prior in the settled era. One-lap sims are far more
    # representative and get more trust as the weekend sharpens.
    # The SPRINT is a real race on race fuel and is the strongest long-run
    # source there is (0.45, and the calibration independently implies 0.41).
    # SPRINT QUALIFYING is the counter-example worth remembering: being a real
    # low-fuel session was assumed to make it a better one-lap read than any
    # practice sim, and the measurement disagrees — a green Friday-evening
    # track with a single practice of setup behind it is not a Saturday
    # quali. See its own note below.
    "base_noise": {
        ("onelap", "Practice 1"): 0.55,
        ("onelap", "Practice 2"): 0.35,
        ("onelap", "Practice 3"): 0.25,
        # RAISED from 0.20 (Aug 2026). The old value was fitted on 2026's four
        # sprint weekends — the holdout — because nothing had ever backfilled
        # sprint sessions from earlier seasons, so there was no other sample.
        # With 2021-25 sprints now cached, the attenuation calibration has 157
        # pre-2026 observations and implies 0.606; the 2026 holdout says 0.634
        # independently. Two disjoint samples agreeing at ~0.61 against a set
        # value of 0.20 means the model was trusting Sprint Qualifying about
        # three times more than it earns. Sensible in hindsight: SQ is a
        # low-fuel qualifying run on a green Friday-evening track with one
        # practice session of setup work behind it, not a Saturday quali.
        ("onelap", "Sprint Qualifying"): 0.60,
        ("longrun", "Practice 1"): 0.85,
        ("longrun", "Practice 2"): 0.70,
        # LEFT AT 0.85 DELIBERATELY. The attenuation calibration
        # (scripts/calibrate_pace_noise.py) is the one place that disagrees
        # with this table: on pre-2026 data the outcome regresses on the FP3
        # long-run gap with slope 0.18±0.05, implying a noise of 1.21. The
        # story is physically plausible (FP3 sits an hour before qualifying,
        # so its "race sims" are short afterthoughts around quali prep) —
        # but raising it to 1.20 and re-running the backtest moved nothing
        # decidable: pre-2026 MAE +0.001 / rho −0.019, 2026 MAE +0.003 /
        # rho +0.004, on 14 and 7 events. The scoring loop is simply too
        # thin at this stage to adjudicate, and swapping a constant that
        # works in use for one an underpowered test cannot confirm is how
        # tuning noise gets baked in. Revisit when FP3 long-run coverage
        # grows; the calibration re-runs in one command.
        ("longrun", "Practice 3"): 0.85,
        ("longrun", "Sprint"): 0.45,
        # Actual qualifying gaps used as a LONG-RUN measurement (the optional
        # post-quali stage): the gap itself is measured almost exactly, so
        # this noise is pure one-lap → race-pace translation error. Matches
        # the prior's stand-in term (sqrt(longrun_from_onelap_var) ≈ 0.55):
        # stronger than any practice race sim, weaker than a real Sprint.
        #
        # This stage is used LIVE but no backtest scores it — they omit
        # quali_gap on purpose to stay leak-free — so it went a long time
        # with no estimation sample at all. calibrate_pace_noise.py now
        # covers it (collect_post_quali). The audit it triggered found a
        # SCALE error rather than a noise error: against the raw
        # best-of-Q1/Q2/Q3 gap the outcome regressed with slope 0.29 over 675
        # pre-2026 team-events, because the earliest-eliminated teams are also
        # the slowest and the green-track penalty compounds their real
        # deficit. Fixed in actual_quali_gap by session-normalising the
        # measurement (slope 1.00 after). With the scale corrected the
        # attenuation identity can no longer identify a positive noise here,
        # so 0.55 stays as the conservative choice rather than being lowered
        # on an estimate that says "zero".
        ("longrun", "Qualifying"): 0.55,
    },
    "default_base_noise": 0.6,
    # ── carry-over across a regulation break ──
    # The prior refuses to look across an era boundary, so at an era opener
    # every team gets the field mean: total amnesia. The archive says that
    # throws away real information — the competitive order survives a
    # regulation change at rho +0.53 (2021->22) and +0.58 (2025->26), against
    # +0.80 for an ordinary winter. Scaling the previous era's closing form by
    # `era_carryover` beat a flat prior at both openings (2022 MAE 0.548 ->
    # 0.503 at k=0.2; 2026 0.748 -> 0.607 at k=1.0).
    #
    # DEFAULT 0.0 — deliberately OFF. The optimum differs wildly between the
    # two openings (0.2 vs 1.0) and there are only two of them ever, so k
    # cannot be fitted, only shown to be positive. Turn it on with a value
    # calibrated on 2022 and validated on 2026, never the reverse. Only ever
    # applies to a team with NO history in the current era; one round in and
    # the normal path takes over.
    #
    # The VARIANCE is deliberately not reduced when this is on: a better
    # guess at the mean is not a reason to claim more confidence, and the
    # measured carry-over is far from perfect.
    "era_carryover": 0.0,
    "era_carryover_rounds": 5,   # closing rounds of the old era to average
    # ── upgrade-aware prior widening ──
    # A team that brings a performance package is less predictable from its
    # own form line than one running a stable car — the whole point of the
    # package is to move the car, and it sometimes moves it backwards. The
    # prior VARIANCE (never the mean: the direction is unknown) is widened by
    # upgrade_var_per_item %² per Performance component declared in the FIA
    # Car Presentation for that event (data/upgrades.csv), capped so a
    # 16-item B-spec (sd contribution ≈ 0.6 %) can't blow the prior open.
    # A-PRIORI constants, deliberately NOT tuned: upgrades.csv only covers
    # 2026 — the holdout season — so any tuning would be holdout leakage.
    "upgrade_var_per_item": 0.04,   # %² per declared performance component
    "upgrade_var_cap": 0.36,        # %² ceiling per event
    # ── outcome simulation ──
    "exec_sd": 0.18,             # % — event-day execution noise per team
    "n_sims": 20000,
}

_UPGRADES_CSV = Path("data/upgrades.csv")
_upgrades_cache: dict = {"mtime": None, "df": None}


def _performance_items(season: int, event: str) -> dict[str, int]:
    """{team: n declared Performance components} for one event; {} when the
    upgrade table is absent or silent on the event."""
    try:
        mtime = _UPGRADES_CSV.stat().st_mtime
    except OSError:
        return {}
    if _upgrades_cache["mtime"] != mtime:
        try:
            u = pd.read_csv(_UPGRADES_CSV, encoding="utf-8-sig")
            u = u[u["category"] == "Performance"].copy()
            u["team"] = u["team"].map(canon)
            _upgrades_cache["df"] = u
            _upgrades_cache["mtime"] = mtime
        except Exception as exc:
            logger.warning("upgrades.csv unreadable: %s", exc)
            return {}
    u = _upgrades_cache["df"]
    m = u[(u["season"] == int(season)) & (u["event"] == str(event))]
    return m.groupby("team").size().to_dict()

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
    # Which columns of team_pace_by_event.csv the season-form prior is built
    # from. The *_pace_pct pair is session-normalised (a two-way team+Q-session
    # fit) and field-median-relative; the *_gap_pct pair is the raw gap to pole
    # / to the fastest team. The raw pair carries ~1% of Q1→Q3 track evolution,
    # which flips on and off as a team's best lap moves between Q-sessions —
    # 19% of round-to-round steps in 2026 — so the prior was partly learning
    # noise. Falls back to the gap columns when the table predates them.
    COL_ONELAP = ("onelap_speed_pct", "quali_result_gap_pct")
    COL_LONGRUN = ("race_pace_pct", "race_pace_gap_pct")

    def __init__(self, pace_csv: str | Path = PACE_CSV, **overrides):
        self.p = {**DEFAULTS, **overrides}
        self._driver_ratings = None            # lazy (needs driver_pace CSV)
        # This reads the CSV directly rather than through tabs.pace_data (a
        # model must not depend on a tab), so it applies the legacy column map
        # itself — otherwise an older table resolves to a column that is not
        # there and the fallback above cannot save it.
        df = apply_pace_legacy_columns(pd.read_csv(pace_csv))
        df["team"] = df["team"].map(canon)
        self.col_onelap = next(
            (c for c in self.COL_ONELAP if c in df.columns), self.COL_ONELAP[-1])
        self.col_longrun = next(
            (c for c in self.COL_LONGRUN if c in df.columns), self.COL_LONGRUN[-1])
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

    def next_round_of(self, season: int) -> int:
        """Round to assume for an event not yet in the pace table (its
        qualifying results haven't reached the archive): one past the
        season's newest round, so the prior draws on every round to date."""
        r = self.pace[self.pace["season"] == season]["round"]
        return int(r.max()) + 1 if len(r) else 1

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

    def _prev_era_form(self, season: int, col: str) -> dict[str, float]:
        """Each team's centred gap over the closing rounds of the PREVIOUS
        era, scaled by `era_carryover`. Empty when carry-over is off or there
        is no earlier era. See the constant's note for why it is off by
        default."""
        k = float(self.p.get("era_carryover", 0.0))
        if k <= 0:
            return {}
        cur = era_of(season)
        prev = self.pace[(self.pace["era"] != cur)
                         & (self.pace["season"] < season)
                         & self.pace[col].notna()]
        if prev.empty:
            return {}
        last_season = int(prev["season"].max())
        tail = prev[prev["season"] == last_season]
        cutoff = tail["round"].max() - int(self.p["era_carryover_rounds"]) + 1
        tail = tail[tail["round"] >= cutoff]
        if tail.empty:
            return {}
        centred = tail[col] - tail.groupby("round")[col].transform("mean")
        form = centred.groupby(tail["team"]).mean()
        form = form - form.mean()
        return (k * form).to_dict()

    def _prior_kind(self, season: int, round_: int, col: str,
                    teams: list[str]) -> pd.DataFrame:
        """EW form prior for one gap column. Teams without history in this
        era fall back to the field mean, or to the previous era's closing
        form when `era_carryover` is enabled."""
        h = self._centered_history(season, round_, col)
        # computed per call, not per team: a team can lack era history while
        # others have plenty (a newcomer mid-era), and the lookup is cheap
        carry = self._prev_era_form(season, col)
        rows = []
        for team in teams:
            g = h[h["team"] == team] if not h.empty else pd.DataFrame()
            if g.empty:
                rows.append({"team": team, "mean": carry.get(team, 0.0),
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
        one = self._prior_kind(season, round_, self.col_onelap, teams)
        lng = self._prior_kind(season, round_, self.col_longrun, teams)
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
                        round_: int | None = None,
                        quali_gap: pd.Series | None = None
                        ) -> dict[str, pd.DataFrame]:
        """Stage-by-stage predictions for one event.

        measurements: pre-extracted team measurements (pace_features format);
        fetched from the session caches when omitted. Returns an ordered dict
        stage-name → state df (team, kind, mean, var, sd).

        quali_gap: optional actual qualifying gaps per team (% to field mean,
        as returned by actual_quali_gap on the Qualifying session only). When
        given, an extra "after Quali" stage is appended in which the real
        quali result updates the LONG-RUN latent only — qualifying is hard
        one-lap evidence and translates to race pace with the noise term
        base_noise[("longrun", "Qualifying")]. The one-lap latent is NEVER
        touched by it, so every pre-quali stage (and any one-lap ledger
        scored against qualifying) stays a genuine before-the-fact
        prediction. Callers that must stay outcome-blind (the backtests)
        simply omit it.
        """
        round_ = round_ if round_ is not None else self.round_of(season, event)
        if round_ is None:
            # Mid-weekend of a new event: quali hasn't reached the results
            # archive yet, so the pace table has no row for it. Treat it as
            # the season's next round — the prior is unaffected (it only
            # uses strictly-earlier rounds) and cached practice measurements
            # update it as usual.
            round_ = self.next_round_of(season)
        if measurements is None:
            measurements, _ = event_measurements(season, event)

        teams = self.teams_of_season(season)
        if measurements is not None and not measurements.empty:
            teams = sorted(set(teams) | set(measurements["team"]))
        state = self.prior(season, round_, teams)

        # A declared performance package makes the team's form line a worse
        # predictor of THIS weekend — widen its prior (variance only, both
        # kinds; the direction of an upgrade is unknown until it runs).
        items = _performance_items(season, event)
        if items:
            per, cap = self.p["upgrade_var_per_item"], self.p["upgrade_var_cap"]
            extra = state["team"].map(
                lambda t: min(items.get(t, 0) * per, cap))
            state["var"] = np.minimum(state["var"] + extra,
                                      self.p["max_prior_var"])

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
        if quali_gap is not None and len(quali_gap) >= 4:
            g = quali_gap.dropna()
            mset = pd.DataFrame({
                "team": [canon(t) for t in g.index],
                "kind": "longrun",
                "gap_pct": (g - g.mean()).values,
                # the quali gap is measured near-exactly; the observation
                # noise is the kind-translation term in base_noise
                "se_pct": 0.05,
                "session": "Qualifying",
            })
            state = self._update_with_set(state, mset)
            _snap("after Quali", state)
        return stages

    # ── live outcome (for the prediction ledger) ──────────────

    @staticmethod
    def actual_quali_gap(laps: pd.DataFrame) -> pd.Series:
        """Per-team qualifying gap to the field MEAN (%), from a loaded
        Qualifying session. Matches the onelap prediction's units so the
        ledger can subtract them. Empty if no qualifying laps present.

        SESSION-NORMALISED where possible. Taking the plain minimum across
        Q1/Q2/Q3 does not merely add noise, it AMPLIFIES the field: the teams
        knocked out earliest are also the slowest, so the green-track penalty
        lands in the same direction as their real deficit. Measured over 675
        pre-2026 team-events, race pace regresses on the raw gap with a slope
        of 0.29 — the raw measure overstates the spread roughly threefold —
        against 1.00 for the normalised one. Feeding the raw version into the
        long-run update therefore pushed the latent apart, and no amount of
        tuning base_noise fixes a scale error.

        The Q1/Q2/Q3 split is not in the lap frame, but the session's cached
        RESULTS carry it and are written at load time, so this works live the
        moment qualifying is loaded. Falls back to the raw minimum when the
        results are unavailable.
        """
        if laps is None or laps.empty or "session" not in laps.columns:
            return pd.Series(dtype=float)
        q = laps[laps["session"].isin(["Qualifying", "Sprint Qualifying"])
                 & laps.get("ValidLap", False)]
        if q.empty:
            return pd.Series(dtype=float)

        norm = PaceModel._normalised_quali_gap(q)
        if norm is not None and len(norm) >= 4:
            return norm

        best = q.groupby(q["Team"].map(canon))["LapTime_s"].min().dropna()
        if len(best) < 4:
            return pd.Series(dtype=float)
        return 100.0 * (best / best.mean() - 1)

    @staticmethod
    def _normalised_quali_gap(q: pd.DataFrame) -> pd.Series | None:
        """Session-normalised team gap from the cached results of the session
        `q` came from, or None when that isn't available."""
        from f1lib.quali_norm import normalised_gap_pct
        import f1lib.data_loader as dl

        try:
            season = str(q["season"].iloc[0])
            meeting = str(q["meeting"].iloc[0])
            session = str(q["session"].iloc[0])
        except (KeyError, IndexError):
            return None
        key = dl._session_key(season, meeting, session)
        for base in (Path(SESSIONS_DIR), Path(SESSIONS_LITE_DIR)):
            path = base / f"{key}__results.parquet"
            if not path.exists():
                continue
            try:
                res = pd.read_parquet(path)
            except Exception:
                continue
            if not {"Q1", "Q2", "Q3", "TeamName"} <= set(res.columns):
                continue
            g = res.copy()
            g["team"] = g["TeamName"].map(canon)
            gaps = normalised_gap_pct(g, entity="team", reducer="min")
            if not gaps:
                return None
            s = pd.Series(gaps, dtype=float)
            # normalised_gap_pct centres on the field MEDIAN; this method's
            # contract (and the ledger that subtracts it) is the field MEAN
            return s - s.mean()
        return None

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
                from f1lib.driver_ratings import DriverRatings
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
