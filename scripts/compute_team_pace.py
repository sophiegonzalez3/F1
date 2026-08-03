"""Build the per-event team pace table -> data/team_pace_by_event.csv.

One row per (season, round, event, team). Two FAMILIES of measure live here and
they answer different questions — see the naming convention below.

ONE-LAP (single flat-out lap, low fuel, max attack)

  quali_gap_pct       RESULT measure. Team's best single qualifying lap (best
                      of Q1/Q2/Q3 across its drivers) as % gap to pole. This is
                      what the timing screen showed on Saturday, so it mixes
                      car pace with how far the team got through the sessions:
                      a Q1 exit sets its best on a green track, a Q3 runner on
                      the most-rubbered track of the weekend. Kept because
                      "where did they actually end up" is a real question, but
                      it is NOT a clean read of car pace.
  quali_pace_pct      PACE measure. The same laps, session-normalised: a
                      two-way fixed-effects fit of log(lap time) on team and
                      Q-session strips out the track evolution between Q1 and
                      Q3, so a Q1 lap and a Q3 lap become comparable. Expressed
                      vs the FIELD MEDIAN, not vs pole, so one team's off
                      weekend does not move everybody else's line. Negative =
                      faster than the median car. This is the momentum series.

RACE PACE (sustained laps on race fuel and wearing tyres)

  race_pace_gap_pct   Team's best driver's MEDIAN fuel- and track-evolution-
                      corrected lap over clean race laps — valid, out of dirty
                      air, and NOT perturbed (no safety car, VSC, yellow or
                      sector anomaly) — as % gap to the event's fastest team.
  race_pace_pct       The same measure expressed vs the FIELD MEDIAN, for the
                      same reason as quali_pace_pct. Negative = faster than the
                      median car. This is the momentum series.
  race_pace_missing   True when the round ran but no race-pace figure could be
                      computed (laps not cached, or under the 10-clean-lap
                      floor). Lets the charts BREAK the line instead of drawing
                      a straight segment through a gap and passing it off as
                      measured data.

CHAMPIONSHIP

  points              constructor points scored that round (race + sprint)
  cum_points          running total up to and including that round

Why two baselines: gap-to-pole and gap-to-fastest are floating references. In
2026 Mercedes was the quali reference for rounds 1-10, so every other team's
line was really a Mercedes-relative line — when the reference has a bad
weekend the whole field appears to improve. The field median barely moves when
one car stumbles, so a line that drops is a team that actually dropped.

Team names are normalised through config.TEAM_COLORS aliases so a team keeps
one identity across seasons.

Usage
-----
    python scripts/compute_team_pace.py                # all seasons in the archive
    python scripts/compute_team_pace.py --season 2026  # one season
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import f1lib.data_loader as dl
from f1lib.processing import (
    clean_and_enrich_laps, flag_dirty_air, flag_perturbed_laps,
    enrich_track_evolution,
)

OUT_PATH = Path("data/team_pace_by_event.csv")
HIST = Path("data/historical_results")

# Historical archive team names → canonical (current) names, so one team is
# one line across seasons. Keys not listed map to themselves.
TEAM_CANON = {
    "RB": "Racing Bulls", "AlphaTauri": "Racing Bulls",
    "Kick Sauber": "Sauber", "Alfa Romeo": "Sauber", "Alfa Romeo Racing": "Sauber",
}


def canon(team: str) -> str:
    return TEAM_CANON.get(str(team).strip(), str(team).strip())


# ─────────────────────────────────────────────────────────────
# Qualifying gap (results archive — covers every round)
# ─────────────────────────────────────────────────────────────

def _session_normalised_pace(g: pd.DataFrame) -> dict[str, float]:
    """Session-normalised one-lap pace for one round, as % vs the field median.

    Fits log(lap time) ~ team + Q-session by least squares on every team's best
    lap in every session it ran (an unbalanced two-way fixed-effects panel).
    The session dummies absorb the track evolution between Q1 and Q3, so a team
    whose best came from Q1 is no longer penalised ~1% for it — which is the
    whole point: 19% of round-to-round steps in 2026 changed which session the
    best lap came from, and that flip alone moved the raw gap by ~0.6 pp.

    Returns {team: pct_vs_field_median}; negative = faster than the median car.
    Empty dict when the round cannot be fitted (caller falls back).
    """
    long = []
    for s in ("Q1", "Q2", "Q3"):
        if s not in g.columns:
            continue
        sub = g[["team", s]].dropna()
        if sub.empty:
            continue
        sub = sub.rename(columns={s: "t"})
        # a team's best lap in THIS session (two cars, keep the quicker)
        sub = sub.groupby("team", as_index=False)["t"].min()
        sub["sess"] = s
        long.append(sub)
    if not long:
        return {}
    L = pd.concat(long, ignore_index=True)
    L = L[L["t"] > 0]
    teams = sorted(L["team"].unique())
    if len(teams) < 2 or L.empty:
        return {}

    # Design: intercept + (n_teams-1) team dummies + (n_sess-1) session dummies.
    # The dropped team is the reference (effect 0); we re-centre on the median
    # afterwards so the choice of reference does not matter.
    T = pd.get_dummies(L["team"], prefix="t", drop_first=True).astype(float)
    S = pd.get_dummies(L["sess"], prefix="s", drop_first=True).astype(float)
    X = np.column_stack([np.ones(len(L)), T.values, S.values]) if len(S.columns) \
        else np.column_stack([np.ones(len(L)), T.values])
    y = np.log(L["t"].to_numpy(dtype=float))
    try:
        beta, _res, rank, _sv = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return {}
    if rank < X.shape[1]:
        # rank-deficient (e.g. a team that ran in exactly one session that no
        # other team ran) — lstsq still returns a min-norm answer, but the team
        # effects are no longer uniquely identified. Don't trust it.
        return {}

    eff = {c[2:]: b for c, b in zip(T.columns, beta[1:1 + len(T.columns)])}
    eff[next(t for t in teams if t not in eff)] = 0.0   # the dropped reference
    med = float(np.median(list(eff.values())))
    out = {t: round((float(np.exp(v - med)) - 1) * 100, 3) for t, v in eff.items()}
    # A sane one-lap field spans a few per cent; anything wilder means the fit
    # went wrong (a red-flagged session, a single-lap sample) — reject it.
    if max(abs(v) for v in out.values()) > 15.0:
        return {}
    return out


def quali_gaps(season: int) -> pd.DataFrame:
    q = pd.read_parquet(HIST / "quali_results_all.parquet")
    q = q[q["season"] == season].copy()
    if q.empty:
        return pd.DataFrame()
    q["best"] = q[["Q1", "Q2", "Q3"]].min(axis=1)
    q["team"] = q["TeamName"].map(canon)
    rows = []
    n_fe = 0
    for (rnd, event), g in q.groupby(["round_number", "event_name"]):
        team_best = g.groupby("team")["best"].min().dropna()
        if team_best.empty:
            continue
        pole = team_best.min()
        fe = _session_normalised_pace(g)
        if fe:
            n_fe += 1
        else:
            # Fall back to the raw gap re-centred on the field median, so the
            # column is never empty — still better than a pole baseline, just
            # without the session correction.
            med = float(team_best.median())
            fe = {t: round((v / med - 1) * 100, 3) for t, v in team_best.items()}
        for team, t in team_best.items():
            rows.append({"season": season, "round": int(rnd), "event": event,
                         "team": team,
                         "quali_gap_pct": round((t / pole - 1) * 100, 3),
                         "quali_pace_pct": fe.get(team, np.nan)})
    if rows:
        n_rounds = len({r["round"] for r in rows})
        print(f"  one-lap pace: session-normalised at {n_fe}/{n_rounds} rounds")
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# Race pace gap (cached race laps — corrected, clean-air medians)
# ─────────────────────────────────────────────────────────────

def race_pace_gaps(season: int, events: list[str]) -> pd.DataFrame:
    rows = []
    for event in events:
        key = dl._session_key(str(season), event, "Race")
        paths = dl._cache_paths(key)
        p = paths["laps"]
        if not p.exists():
            continue
        # Race-control messages are optional: without them flag_perturbed_laps
        # still catches safety cars and VSCs from the per-lap TrackStatus
        # column, but it misses the short sector yellows that never reach it.
        rcm = None
        if paths["race_control"].exists():
            try:
                rcm = pd.read_parquet(paths["race_control"])
            except Exception as exc:
                print(f"  [{season} {event}] race control unreadable ({exc})")
        try:
            fl = clean_and_enrich_laps(pd.read_parquet(p))
            # ORDER MATTERS — do not reorder. flag_perturbed_laps must run
            # BEFORE enrich_track_evolution: the evolution fit only drops
            # safety-car / VSC / yellow laps when Perturbed_Lap already exists,
            # and fitting on them wrecks the measurement. compute_car_profile.py
            # measured the same mistake at split-half reliability 0.17 (noise)
            # against 0.69 with the correct order; here it moved a team's race
            # pace by up to 0.46 pp in a single event.
            fl = enrich_track_evolution(
                flag_dirty_air(flag_perturbed_laps(fl, rcm=rcm)))
        except Exception as exc:
            print(f"  [{season} {event}] race pipeline failed: {exc}")
            continue
        y = ("LapTime_TrackCorrected" if "LapTime_TrackCorrected" in fl.columns
             else "LapTime_FuelCorrected")
        # Perturbed laps are excluded from the median too, not just from the
        # evolution fit — a VSC lap under the 1.25x outlier ceiling is still a
        # slow lap and has no place in a car-pace measurement.
        clean = fl[fl["ValidLap"]
                   & ~fl.get("Dirty_Air", False)
                   & ~fl.get("Perturbed_Lap", False)]
        med = clean.groupby(["Team", "Driver_Short"])[y].median()
        # a driver needs a real race's worth of clean laps to count
        n = clean.groupby(["Team", "Driver_Short"])[y].count()
        med = med[n >= 10]
        if med.empty:
            continue
        team_best = med.groupby("Team").min()
        best = team_best.min()
        field_med = float(team_best.median())
        for team, t in team_best.items():
            rows.append({"season": season, "event": event, "team": canon(team),
                         "race_pace_gap_pct": round((t / best - 1) * 100, 3),
                         "race_pace_pct": round((t / field_med - 1) * 100, 3)})
        print(f"  [{season} {event}] race pace: {len(team_best)} teams")
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# Points (race + sprint)
# ─────────────────────────────────────────────────────────────

def round_points(season: int) -> pd.DataFrame:
    frames = []
    for fname in ("race_results_all.parquet", "sprint_results_all.parquet"):
        p = HIST / fname
        if p.exists():
            df = pd.read_parquet(p)
            frames.append(df[df["season"] == season])
    if not frames:
        return pd.DataFrame()
    res = pd.concat(frames, ignore_index=True)
    if res.empty:
        return pd.DataFrame()
    res["team"] = res["TeamName"].map(canon)
    pts = (res.groupby(["round_number", "team"])["Points"].sum()
           .reset_index()
           .rename(columns={"round_number": "round", "Points": "points"}))
    pts["season"] = season
    return pts


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def build_season(season: int) -> pd.DataFrame:
    qg = quali_gaps(season)
    if qg.empty:
        print(f"[{season}] no qualifying results in the archive — skipped")
        return pd.DataFrame()
    events_in_order = (qg.drop_duplicates("round")
                       .sort_values("round")["event"].tolist())
    rp = race_pace_gaps(season, events_in_order)
    pts = round_points(season)

    out = qg
    if not rp.empty:
        out = out.merge(rp, on=["season", "event", "team"], how="left")
    else:
        out["race_pace_gap_pct"] = np.nan
        out["race_pace_pct"] = np.nan
    # Explicit "the round ran but we have no race pace for it" flag, so the
    # charts can break the line instead of interpolating across the hole.
    out["race_pace_missing"] = out["race_pace_pct"].isna()
    if not pts.empty:
        out = out.merge(pts, on=["season", "round", "team"], how="left")
    else:
        out["points"] = np.nan
    out["points"] = out["points"].fillna(0.0)
    out = out.sort_values(["team", "round"])
    out["cum_points"] = out.groupby("team")["points"].cumsum()
    return out.sort_values(["round", "quali_gap_pct"]).reset_index(drop=True)


def main() -> int:
    if "--season" in sys.argv:
        seasons = [int(sys.argv[sys.argv.index("--season") + 1])]
    else:
        q = pd.read_parquet(HIST / "quali_results_all.parquet")
        seasons = sorted(q["season"].unique())
    frames = []
    for season in seasons:
        print(f"[{season}] building…")
        df = build_season(int(season))
        if not df.empty:
            frames.append(df)
    if not frames:
        print("Nothing built.")
        return 1
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(OUT_PATH, index=False)
    n_rp = out["race_pace_gap_pct"].notna().sum()
    n_qp = out["quali_pace_pct"].notna().sum()
    print(f"\nWrote {len(out)} rows -> {OUT_PATH} "
          f"({n_rp} with race pace, {n_qp} with one-lap pace, "
          f"{out['season'].nunique()} seasons)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
