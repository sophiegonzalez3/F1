"""Build the per-event team pace table -> data/team_pace_by_event.csv.

One row per (season, round, event, team) with the season-long pace measures
that the SEASON tab and the Upgrade Impact analysis consume:

  quali_gap_pct      team's best single qualifying lap (best of Q1/Q2/Q3
                     across its drivers) as % gap to pole. Comes from the
                     historical results archive, so it covers EVERY round of
                     a season, cached laps or not.
  race_pace_gap_pct  team's best driver race pace (median fuel- and
                     track-evolution-corrected lap on clean, valid,
                     non-dirty-air laps) as % gap to the event's fastest
                     team. Needs the race laps Parquet, so it exists only
                     for rounds cached under data/sessions/.
  points             constructor points scored that round (race + sprint)
  cum_points         running total up to and including that round

Team names are normalised through config.TEAM_COLORS aliases so a team keeps
one identity across seasons.

Usage
-----
    python compute_team_pace.py                # all seasons in the archive
    python compute_team_pace.py --season 2026  # one season
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import data_loader as dl
from processing import clean_and_enrich_laps, flag_dirty_air, enrich_track_evolution

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

def quali_gaps(season: int) -> pd.DataFrame:
    q = pd.read_parquet(HIST / "quali_results_all.parquet")
    q = q[q["season"] == season].copy()
    if q.empty:
        return pd.DataFrame()
    q["best"] = q[["Q1", "Q2", "Q3"]].min(axis=1)
    q["team"] = q["TeamName"].map(canon)
    rows = []
    for (rnd, event), g in q.groupby(["round_number", "event_name"]):
        team_best = g.groupby("team")["best"].min().dropna()
        if team_best.empty:
            continue
        pole = team_best.min()
        for team, t in team_best.items():
            rows.append({"season": season, "round": int(rnd), "event": event,
                         "team": team,
                         "quali_gap_pct": round((t / pole - 1) * 100, 3)})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# Race pace gap (cached race laps — corrected, clean-air medians)
# ─────────────────────────────────────────────────────────────

def race_pace_gaps(season: int, events: list[str]) -> pd.DataFrame:
    rows = []
    for event in events:
        key = dl._session_key(str(season), event, "Race")
        p = dl._cache_paths(key)["laps"]
        if not p.exists():
            continue
        try:
            fl = clean_and_enrich_laps(pd.read_parquet(p))
            fl = flag_dirty_air(fl)
            fl = enrich_track_evolution(fl)
        except Exception as exc:
            print(f"  [{season} {event}] race pipeline failed: {exc}")
            continue
        y = ("LapTime_TrackCorrected" if "LapTime_TrackCorrected" in fl.columns
             else "LapTime_FuelCorrected")
        clean = fl[fl["ValidLap"] & ~fl.get("Dirty_Air", False)]
        med = clean.groupby(["Team", "Driver_Short"])[y].median()
        # a driver needs a real race's worth of clean laps to count
        n = clean.groupby(["Team", "Driver_Short"])[y].count()
        med = med[n >= 10]
        if med.empty:
            continue
        team_best = med.groupby("Team").min()
        best = team_best.min()
        for team, t in team_best.items():
            rows.append({"season": season, "event": event, "team": canon(team),
                         "race_pace_gap_pct": round((t / best - 1) * 100, 3)})
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
    print(f"\nWrote {len(out)} rows -> {OUT_PATH} "
          f"({n_rp} with race pace, {out['season'].nunique()} seasons)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
